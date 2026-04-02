"""ResultStore — unified interface for simulation results (DuckDB + Zarr)."""

from __future__ import annotations

import json
import logging
import time
import warnings
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
import numpy as np
import pandas as pd
import zarr

from hydromodpy.simulation.results.provenance import fingerprint, verify_fingerprint
from hydromodpy.simulation.results.schema import (
    PROJECT_TABLE_NAMES,
    create_project_tables,
    create_registry_table,
)
from hydromodpy.simulation.results.spatial_index import point_in_cell
from hydromodpy.simulation.results.zarr_layout import (
    create_simulation_group,
    write_field_chunk,
    write_mesh_arrays,
)

logger = logging.getLogger(__name__)

_REGISTRY_RETRY = 3
_REGISTRY_BACKOFF = 0.1  # seconds


class ResultStore:
    """Unified read/write interface for simulation results.

    Stores metadata and time series in DuckDB, spatial fields in Zarr v3.
    Optionally connects to a workspace-level catalog for cross-project
    simulation discovery.

    Parameters
    ----------
    project_path : Path
        Directory containing (or to contain) ``project.duckdb`` and
        ``project_results.zarr``.
    workspace_path : Path, optional
        Workspace root containing ``catalog.duckdb``. When provided,
        :meth:`finalize` populates ``simulation_registry`` and
        :meth:`delete_simulation` cleans it up.
    """

    def __init__(
        self,
        project_path: Path | str,
        workspace_path: Path | str | None = None,
    ) -> None:
        self._project_path = Path(project_path)
        self._project_path.mkdir(parents=True, exist_ok=True)

        db_path = self._project_path / "project.duckdb"
        self._db = duckdb.connect(str(db_path))
        create_project_tables(self._db)

        self._zarr_path = str(self._project_path / "project_results.zarr")

        self._workspace_path = Path(workspace_path) if workspace_path else None
        self._catalog_path = (
            self._workspace_path / "catalog.duckdb"
            if self._workspace_path
            else None
        )
        if self._catalog_path is not None:
            self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
            cat = duckdb.connect(str(self._catalog_path))
            create_registry_table(cat)
            cat.close()

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- Write methods ---------------------------------------------------------

    def register_simulation(
        self,
        sim_id: str | UUID,
        config: dict | None = None,
        *,
        name: str | None = None,
        solver: str | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
        n_timesteps: int | None = None,
        cell_types: list[str] | None = None,
        bbox: list[float] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register a new simulation run."""
        sid = str(sim_id)
        config_json = json.dumps(config) if config else None
        zarr_group = sid

        self._db.execute(
            """INSERT INTO simulations
               (sim_id, name, config_toml, solver, n_cells, n_layers,
                n_timesteps, cell_types, bbox, zarr_group, status, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            [
                sid, name, config_json, solver, n_cells, n_layers,
                n_timesteps, cell_types, bbox, zarr_group, tags,
            ],
        )

        if n_cells is not None and n_layers is not None:
            create_simulation_group(
                self._zarr_path, sid,
                n_cells=n_cells, n_layers=n_layers, cell_types=cell_types,
            )

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
    ) -> None:
        """Write mesh topology into Zarr."""
        root = zarr.open_group(self._zarr_path, mode="a")
        grp = root[str(sim_id)]
        write_mesh_arrays(
            grp, vertices, face_node_connectivity, z_interfaces,
            layer_indices=layer_indices,
            source_cell_indices=source_cell_indices,
        )

    def write_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        subgroup: str | None = None,
    ) -> None:
        """Write one timestep of a spatial field into Zarr."""
        root = zarr.open_group(self._zarr_path, mode="a")
        grp = root[str(sim_id)]
        write_field_chunk(
            grp, variable, timestep, values,
            n_timesteps=n_timesteps, subgroup=subgroup,
        )

    def write_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        ts: pd.Series,
        unit: str = "",
    ) -> None:
        """Write a point time series into DuckDB."""
        timestamps = ts.index.tolist()
        values = ts.values.tolist()
        self._db.execute(
            """INSERT INTO timeseries
               (sim_id, station_id, variable, timestamps, values, unit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(sim_id), station_id, variable, timestamps, values, unit],
        )

    def write_budget(
        self,
        sim_id: str | UUID,
        timestep: int,
        zone_id: int,
        component: str,
        flux_in: float,
        flux_out: float,
        unit: str = "m3/d",
    ) -> None:
        """Write one budget record into DuckDB."""
        self._db.execute(
            """INSERT INTO budgets
               (sim_id, timestep, zone_id, component, flux_in, flux_out, unit)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [str(sim_id), timestep, zone_id, component, flux_in, flux_out, unit],
        )

    def write_mass_balance(
        self,
        sim_id: str | UUID,
        timestep: int,
        total_in: float,
        total_out: float,
        percent_error: float,
        storage_in: float = 0.0,
        storage_out: float = 0.0,
    ) -> None:
        """Write one mass balance record into DuckDB."""
        self._db.execute(
            """INSERT INTO mass_balance_summary
               (sim_id, timestep, total_in, total_out,
                storage_in, storage_out, percent_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id), timestep, total_in, total_out,
                storage_in, storage_out, percent_error,
            ],
        )

    def record_provenance(
        self,
        sim_id: str | UUID,
        variable: str,
        source_ref: str,
        data: np.ndarray,
        *,
        source_type: str = "data_manager",
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        """Record a fingerprint (hash + stats) of forcing data."""
        fp = fingerprint(data)
        self._db.execute(
            """INSERT INTO input_provenance
               (sim_id, variable, source_type, source_ref,
                period_start, period_end, checksum, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id), variable, source_type, source_ref,
                period_start, period_end,
                fp["checksum"],
                int(np.prod(data.shape)),
                json.dumps(fp["stats"]),
            ],
        )

    def register_observation_points(
        self,
        sim_id: str | UUID,
        points: dict[str, tuple[float, float]],
        variable: str = "head",
        layer: int = 0,
    ) -> None:
        """Register observation points with point-in-cell mapping."""
        sid = str(sim_id)
        root = zarr.open_group(self._zarr_path, mode="r")
        grp = root[sid]
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]

        mapping = point_in_cell(vertices, connectivity, points)
        for station_id, (x, y) in points.items():
            cell_id = mapping[station_id]
            self._db.execute(
                """INSERT INTO observation_points
                   (sim_id, station_id, x, y, cell_id, layer, variable)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [sid, station_id, x, y, cell_id, layer, variable],
            )

    def finalize(
        self,
        sim_id: str | UUID,
        status: str = "completed",
        duration_s: float | None = None,
    ) -> None:
        """Mark a simulation as finished and update the registry."""
        sid = str(sim_id)
        self._db.execute(
            "UPDATE simulations SET status = ?, duration_s = ? WHERE sim_id = ?",
            [status, duration_s, sid],
        )

        if self._catalog_path is None:
            return

        row = self._db.execute(
            "SELECT * FROM simulations WHERE sim_id = ?", [sid]
        ).fetchone()
        if row is None:
            return

        cols = [d[0] for d in self._db.description]
        sim = dict(zip(cols, row))

        best_nse = self._db.execute(
            "SELECT MAX(value) FROM metrics WHERE sim_id = ? AND metric_name = 'nse'",
            [sid],
        ).fetchone()[0]
        best_kge = self._db.execute(
            "SELECT MAX(value) FROM metrics WHERE sim_id = ? AND metric_name = 'kge'",
            [sid],
        ).fetchone()[0]
        best_rmse = self._db.execute(
            "SELECT MIN(value) FROM metrics WHERE sim_id = ? AND metric_name = 'rmse'",
            [sid],
        ).fetchone()[0]
        n_obs = self._db.execute(
            "SELECT COUNT(DISTINCT station_id) FROM observation_points WHERE sim_id = ?",
            [sid],
        ).fetchone()[0]

        forcing = self._db.execute(
            "SELECT DISTINCT source_ref FROM input_provenance WHERE sim_id = ?",
            [sid],
        ).fetchall()
        forcing_sources = [r[0] for r in forcing] if forcing else None

        config_hash = None
        if sim.get("config_toml"):
            import hashlib
            config_hash = hashlib.sha256(
                json.dumps(sim["config_toml"], sort_keys=True).encode()
            ).hexdigest()

        project_name = self._project_path.name
        project_path = str(self._project_path / "project.duckdb")

        self._write_to_registry({
            "sim_id": sid,
            "project": project_name,
            "project_path": project_path,
            "name": sim.get("name"),
            "solver": sim.get("solver", "unknown"),
            "process_types": None,
            "status": status,
            "n_cells": sim.get("n_cells"),
            "n_layers": sim.get("n_layers"),
            "cell_types": sim.get("cell_types"),
            "bbox": sim.get("bbox"),
            "crs": None,
            "n_timesteps": sim.get("n_timesteps"),
            "period_start": None,
            "period_end": None,
            "time_unit": None,
            "duration_s": duration_s or sim.get("duration_s"),
            "best_nse": best_nse,
            "best_kge": best_kge,
            "best_rmse": best_rmse,
            "n_observation_points": n_obs,
            "forcing_sources": forcing_sources,
            "config_hash": config_hash,
        })

    def _write_to_registry(self, row: dict) -> None:
        """Insert into simulation_registry with retry for concurrency."""
        for attempt in range(_REGISTRY_RETRY):
            try:
                cat = duckdb.connect(str(self._catalog_path))
                cat.execute(
                    """INSERT OR REPLACE INTO simulation_registry
                       (sim_id, project, project_path, name, solver,
                        process_types, status, n_cells, n_layers, cell_types,
                        bbox, crs, n_timesteps, period_start, period_end,
                        time_unit, duration_s, best_nse, best_kge, best_rmse,
                        n_observation_points, forcing_sources, config_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?, ?, ?, ?)""",
                    list(row.values()),
                )
                cat.close()
                return
            except duckdb.IOException:
                if attempt < _REGISTRY_RETRY - 1:
                    time.sleep(_REGISTRY_BACKOFF * (2 ** attempt))
                else:
                    raise

    # -- Read methods ----------------------------------------------------------

    def list_simulations(self, **filters) -> pd.DataFrame:
        """List simulations, optionally filtered by column values."""
        query = "SELECT * FROM simulations"
        params = []
        if filters:
            clauses = []
            for col, val in filters.items():
                clauses.append(f"{col} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)
        return self._db.execute(query, params).fetchdf()

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
    ) -> pd.Series:
        """Extract a point time series from DuckDB."""
        row = self._db.execute(
            """SELECT timestamps, values, unit FROM timeseries
               WHERE sim_id = ? AND station_id = ? AND variable = ?""",
            [str(sim_id), station_id, variable],
        ).fetchone()
        if row is None:
            raise KeyError(
                f"No timeseries for sim={sim_id}, station={station_id}, var={variable}"
            )
        ts = pd.Series(row[1], index=pd.DatetimeIndex(row[0]), name=variable)
        if period is not None:
            ts = ts.loc[period[0]:period[1]]
        return ts

    def query_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        """Load a spatial field for one timestep from Zarr."""
        root = zarr.open_group(self._zarr_path, mode="r")
        grp = root[str(sim_id)]

        # Check root then subgroups
        for loc in (grp, grp.get("derived"), grp.get("budget")):
            if loc is not None and variable in loc:
                arr = loc[variable]
                data = arr[timestep]
                if layer is not None and data.ndim == 2:
                    return data[layer]
                return data
        raise KeyError(f"Variable '{variable}' not found for sim={sim_id}")

    def query_budget(
        self,
        sim_id: str | UUID,
        zone_id: int | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        """Query budget records from DuckDB."""
        query = "SELECT * FROM budgets WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if zone_id is not None:
            query += " AND zone_id = ?"
            params.append(zone_id)
        if period is not None:
            query += " AND timestep >= ? AND timestep <= ?"
            params.extend(period)
        return self._db.execute(query, params).fetchdf()

    def query_mass_balance(self, sim_id: str | UUID) -> pd.DataFrame:
        """Return mass balance records for a simulation."""
        return self._db.execute(
            "SELECT * FROM mass_balance_summary WHERE sim_id = ? ORDER BY timestep",
            [str(sim_id)],
        ).fetchdf()

    def get_provenance(
        self,
        sim_id: str | UUID,
        variable: str | None = None,
    ) -> pd.DataFrame:
        """Return input provenance records."""
        query = "SELECT * FROM input_provenance WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if variable is not None:
            query += " AND variable = ?"
            params.append(variable)
        return self._db.execute(query, params).fetchdf()

    def verify_provenance(
        self,
        sim_id: str | UUID,
        variable: str,
        current_data: np.ndarray,
    ) -> bool:
        """Check whether current data matches the stored fingerprint."""
        row = self._db.execute(
            "SELECT checksum FROM input_provenance WHERE sim_id = ? AND variable = ?",
            [str(sim_id), variable],
        ).fetchone()
        if row is None:
            raise KeyError(f"No provenance for sim={sim_id}, var={variable}")
        stored = {"checksum": row[0]}
        return verify_fingerprint(stored, current_data)

    def compare(
        self,
        sim_a: str | UUID,
        sim_b: str | UUID,
        variable: str,
        timestep: int,
    ) -> dict:
        """Compute difference statistics between two simulations."""
        field_a = self.query_field(sim_a, variable, timestep)
        field_b = self.query_field(sim_b, variable, timestep)
        diff = field_a - field_b
        return {
            "mean_diff": float(np.nanmean(diff)),
            "max_abs_diff": float(np.nanmax(np.abs(diff))),
            "rmse": float(np.sqrt(np.nanmean(diff ** 2))),
        }

    # -- Calibration -----------------------------------------------------------

    def extract_calibration_vector(
        self,
        sim_id: str | UUID,
        observation_plan: list[tuple[str, str, list]],
    ) -> np.ndarray:
        """Build a 1D vector of simulated values aligned with observations.

        Parameters
        ----------
        observation_plan : list of (station_id, variable, timestamps)
            Each entry defines which station, variable, and time points
            to extract.
        """
        parts = []
        for station_id, variable, timestamps in observation_plan:
            ts = self.query_timeseries(sim_id, station_id, variable)
            ts_reindexed = ts.reindex(pd.DatetimeIndex(timestamps))
            parts.append(ts_reindexed.values)
        return np.concatenate(parts)

    # -- Export ----------------------------------------------------------------

    def export(
        self,
        sim_id: str | UUID,
        variable: str,
        fmt: str,
        path: Path | str,
        **kwargs,
    ) -> Path:
        """Export results to a standard format (placeholder for Phase 4)."""
        raise NotImplementedError(f"Export format '{fmt}' not yet implemented")

    # -- Delete ----------------------------------------------------------------

    def delete_simulation(self, sim_id: str | UUID) -> None:
        """Remove a simulation from all stores."""
        sid = str(sim_id)

        for table in PROJECT_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])

        try:
            root = zarr.open_group(self._zarr_path, mode="a")
            if sid in root:
                del root[sid]
        except Exception:
            logger.warning("Could not delete Zarr group for %s", sid)

        if self._catalog_path is not None:
            for attempt in range(_REGISTRY_RETRY):
                try:
                    cat = duckdb.connect(str(self._catalog_path))
                    cat.execute(
                        "DELETE FROM simulation_registry WHERE sim_id = ?",
                        [sid],
                    )
                    cat.close()
                    return
                except duckdb.IOException:
                    if attempt < _REGISTRY_RETRY - 1:
                        time.sleep(_REGISTRY_BACKOFF * (2 ** attempt))
                    else:
                        raise
