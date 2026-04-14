from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import duckdb
import numpy as np
import pandas as pd

from hydromodpy.results.catalog_schema import (
    HOMOGENEOUS_ZONE,
    PER_SIM_TABLE_NAMES,
    SOLVER_CATEGORIES,
    ensure_schema,
)
from hydromodpy.results.provenance import fingerprint
from hydromodpy.results.spatial_index import point_in_cell
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)


class SimulationCatalog:

    def __init__(self, workspace_path: Path | str) -> None:
        self._workspace = Path(workspace_path)
        self._workspace.mkdir(parents=True, exist_ok=True)

        self._db_path = self._workspace / "hydromodpy.duckdb"
        self._db = duckdb.connect(str(self._db_path))
        ensure_schema(self._db)

        self._simulations_dir = self._workspace / "simulations"
        self._simulations_dir.mkdir(exist_ok=True)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._db

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    # -- Registration --------------------------------------------------------

    def register_simulation(
        self,
        sim_id: str | UUID,
        project: str,
        solver: str,
        *,
        name: str | None = None,
        solver_category: str | None = None,
        flow_regime: str | None = None,
        config: dict | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
        n_timesteps: int | None = None,
        cell_types: list[str] | None = None,
        bbox: list[float] | None = None,
        crs: str | None = None,
        period_start: Any = None,
        period_end: Any = None,
        time_unit: str | None = None,
        parent_sim_id: str | UUID | None = None,
        mesh_hash: str | None = None,
        mesh_type: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        run_id: str | None = None,
    ) -> SimulationZarr | None:
        sid = str(sim_id)

        if run_id:
            existing = self._db.execute(
                "SELECT sim_id FROM simulations WHERE name = ?", [run_id],
            ).fetchall()
            for (old_sid,) in existing:
                self.delete(old_sid)
                logger.info("Replaced previous simulation %s (run_id=%s)", old_sid, run_id)

        if solver_category is None:
            solver_category = SOLVER_CATEGORIES.get(solver)

        config_json = json.dumps(config) if config else None
        config_hash = None
        if config:
            config_hash = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()

        zarr_path = f"simulations/{sid}.zarr"
        parent_sid = str(parent_sim_id) if parent_sim_id else None
        p_start = str(period_start) if period_start is not None else None
        p_end = str(period_end) if period_end is not None else None

        self._db.execute(
            """INSERT INTO simulations
               (sim_id, name, project, solver, solver_category, flow_regime,
                n_cells, n_layers, n_timesteps, cell_types, bbox, crs,
                period_start, period_end, time_unit,
                config_toml, config_hash, zarr_path,
                parent_sim_id, mesh_hash, mesh_type, tags, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)""",
            [
                sid, name, project, solver, solver_category, flow_regime,
                n_cells, n_layers, n_timesteps, cell_types, bbox, crs,
                p_start, p_end, time_unit,
                config_json, config_hash, zarr_path,
                parent_sid, mesh_hash, mesh_type, tags, notes,
            ],
        )

        if n_cells is not None and n_layers is not None:
            zarr_abs = self._workspace / zarr_path
            return SimulationZarr.create(
                zarr_abs, n_cells=n_cells, n_layers=n_layers,
                cell_types=cell_types,
            )
        return None

    # -- Parameter writes ----------------------------------------------------

    def write_parameters(
        self,
        sim_id: str | UUID,
        params: list[dict],
    ) -> None:
        sid = str(sim_id)
        for p in params:
            zone = p.get("zone_id")
            zone_val = HOMOGENEOUS_ZONE if zone is None else str(zone)
            self._db.execute(
                """INSERT INTO parameters
                   (sim_id, param_name, zone_id, value, unit, parameterization)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    sid, p["param_name"], zone_val,
                    p.get("value"), p.get("unit"), p.get("parameterization"),
                ],
            )

    # -- Timeseries ----------------------------------------------------------

    def write_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        ts: pd.Series,
        unit: str = "",
    ) -> None:
        n = len(ts)
        if n == 0:
            return
        sid = str(sim_id)
        insert_df = pd.DataFrame(
            {
                "sim_id": np.full(n, sid, dtype=object),
                "station_id": np.full(n, station_id, dtype=object),
                "variable": np.full(n, variable, dtype=object),
                "timestamp": ts.index,
                "value": ts.values.astype("float64"),
                "unit": np.full(n, unit, dtype=object),
            }
        )
        self._db.execute(
            "INSERT INTO timeseries "
            "(sim_id, station_id, variable, timestamp, value, unit) "
            "SELECT sim_id, station_id, variable, timestamp, value, unit "
            "FROM insert_df"
        )

    # -- Budget --------------------------------------------------------------

    def write_budget(
        self,
        sim_id: str | UUID,
        timestep: int,
        zone_id: str,
        component: str,
        flux_in: float,
        flux_out: float,
        unit: str = "m3/d",
    ) -> None:
        self._db.execute(
            """INSERT INTO budgets
               (sim_id, timestep, zone_id, component, flux_in, flux_out, unit)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [str(sim_id), timestep, zone_id, component, flux_in, flux_out, unit],
        )

    # -- Mass balance --------------------------------------------------------

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
        self._db.execute(
            """INSERT INTO mass_balance
               (sim_id, timestep, total_in, total_out,
                storage_in, storage_out, percent_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id), timestep, total_in, total_out,
                storage_in, storage_out, percent_error,
            ],
        )

    # -- Metrics -------------------------------------------------------------

    def write_metric(
        self,
        sim_id: str | UUID,
        station_id: str,
        metric_name: str,
        value: float,
    ) -> None:
        self._db.execute(
            """INSERT OR REPLACE INTO metrics
               (sim_id, station_id, metric_name, value)
               VALUES (?, ?, ?, ?)""",
            [str(sim_id), station_id, metric_name, value],
        )

    # -- Provenance ----------------------------------------------------------

    def write_provenance(
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
        fp = fingerprint(data)
        self._db.execute(
            """INSERT INTO provenance
               (sim_id, variable, source_type, source_ref,
                period_start, period_end, checksum, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id), variable, source_type, source_ref,
                str(period_start) if period_start is not None else None,
                str(period_end) if period_end is not None else None,
                fp["checksum"],
                int(np.prod(data.shape)),
                json.dumps(fp["stats"]),
            ],
        )

    # -- Observation points --------------------------------------------------

    def register_observation_points(
        self,
        sim_id: str | UUID,
        points: dict[str, tuple[float, float]],
        variable: str = "head",
        layer: int = 0,
    ) -> None:
        sid = str(sim_id)
        sz = self.open_zarr(sim_id)
        mesh = sz.root["mesh"]
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

    # -- Geographic (project-scoped) -----------------------------------------

    def write_geographic_feature(
        self,
        project: str,
        feature_name: str,
        gdf: gpd.GeoDataFrame,
    ) -> None:
        if gdf.empty:
            return
        geojson_str = gdf.to_json()
        from shapely.ops import unary_union
        union_geom = unary_union(
            [g for g in gdf.geometry if g is not None and not g.is_empty]
        )
        geom_type = union_geom.geom_type
        crs_str = str(gdf.crs) if gdf.crs else ""

        self._db.execute(
            "INSERT OR REPLACE INTO geographic_features "
            "(project, feature_name, geojson, geometry_type, crs, properties) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            [project, feature_name, geojson_str, geom_type, crs_str],
        )

    def write_geographic_metadata(
        self,
        project: str,
        metadata: dict[str, str],
    ) -> None:
        for key, value in metadata.items():
            self._db.execute(
                "INSERT OR REPLACE INTO geographic_metadata (project, key, value) "
                "VALUES (?, ?, ?)",
                [project, str(key), str(value)],
            )

    # -- Zarr access ---------------------------------------------------------

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        zarr_path = self._simulations_dir / f"{sim_id}.zarr"
        return SimulationZarr(zarr_path)

    # -- Lifecycle -----------------------------------------------------------

    def finalize(
        self,
        sim_id: str | UUID,
        status: str = "completed",
        duration_s: float | None = None,
    ) -> None:
        self._db.execute(
            "UPDATE simulations SET status = ?, duration_s = ? WHERE sim_id = ?",
            [status, duration_s, str(sim_id)],
        )

    def delete(self, sim_id: str | UUID) -> None:
        sid = str(sim_id)

        row = self._db.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?", [sid],
        ).fetchone()

        for table in PER_SIM_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

        if row and row[0]:
            zarr_abs = self._workspace / row[0]
            if zarr_abs.exists():
                shutil.rmtree(zarr_abs, ignore_errors=True)

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
