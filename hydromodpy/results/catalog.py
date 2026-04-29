"""Catalog facade for the results layer.

What
----
Central registry for finished simulations. Backed by DuckDB for tabular state
(simulations, parameters, metrics, provenance, calibration sessions) and by
Zarr / Parquet for field arrays and timeseries written under the workspace.

Why
---
Solver outputs land in heterogeneous formats (binary heads, CSV budgets, mesh
files). The catalog keeps one durable index keyed by ``sim_id`` so downstream
``Run`` and ``SimulationGroup`` views can resolve, filter, and read results
without each caller re-implementing storage paths.

Public API
----------
- ``SimulationCatalog``: connection-managed entry point. Methods cover
  registration (``register_simulation``), per-simulation writers
  (``write_parameters``, ``write_timeseries``, ``write_budget``,
  ``write_field``, ``write_mesh`` ...), readers / queries (``query_field``,
  ``query_timeseries``, ``list_simulations``, ``sql``), reference resolution
  (``resolve``, ``__getitem__``, ``find``, ``latest``, ``best``), and lifecycle
  helpers (``finalize``, ``cleanup``, ``export_package``, ``import_package``,
  ``delete``).
- ``RegistrationResult``: dataclass returned by ``register_simulation``.
- Errors: ``SimulationNotFoundError``, ``AmbiguousReferenceError``,
  ``DuplicateSimulationNameError``.

Cross-refs
----------
- ``hydromodpy.results.run.Run`` and
  ``hydromodpy.results.simulation_group.SimulationGroup`` consume this facade.
- ``hydromodpy.results.catalog_schema`` defines the DuckDB schema and parquet
  view bindings.
- ``hydromodpy.results.zarr_store.SimulationZarr`` owns field-array storage.
- ``hydromodpy.results.storage_naming`` and
  ``hydromodpy.results.provenance`` build canonical paths and fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import duckdb
import numpy as np
import pandas as pd

from hydromodpy.results._db_retry import connect_with_retry, with_lock_retry
from hydromodpy.results.catalog_schema import (
    GLOBAL_ZONE,
    PER_SIM_TABLE_NAMES,
    ensure_parquet_views,
    ensure_schema,
)
from hydromodpy.results.catalog_schema import (
    solver_category as _resolve_solver_category,
)
from hydromodpy.results.provenance import fingerprint
from hydromodpy.results.spatial_index import point_in_cell
from hydromodpy.results.storage_naming import build_storage_basename
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.run import Run
    from hydromodpy.results.simulation_group import SimulationGroup

logger = logging.getLogger(__name__)

# Reference-resolution helpers -------------------------------------------------

OnCollisionMode = Literal["replace", "fail", "version"]
_MIN_PREFIX_LEN = 4
_UUID_FULL_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)


def short_id(sim_id: str | UUID) -> str:
    """Return the first 8 hex characters of a simulation UUID (Git-style)."""
    return str(sim_id)[:8]


class SimulationNotFoundError(KeyError):
    """Raised when a reference does not match any simulation in the catalog."""


class AmbiguousReferenceError(KeyError):
    """Raised when a UUID prefix matches more than one simulation."""

    def __init__(self, ref: str, candidates: list[tuple[str, str | None]]) -> None:
        self.ref = ref
        self.candidates = candidates
        head = candidates[:10]
        lines = "\n".join(f"  {short_id(sid)}  {name or '(no name)'}" for sid, name in head)
        suffix = f"\n  … and {len(candidates) - 10} more" if len(candidates) > 10 else ""
        super().__init__(
            f"Reference '{ref}' is ambiguous; matches {len(candidates)} "
            f"simulations:\n{lines}{suffix}"
        )


class DuplicateSimulationNameError(ValueError):
    """Raised when on_collision='fail' and a (project, name) pair already exists."""

    def __init__(self, project: str, name: str, existing_sim_id: str) -> None:
        self.project = project
        self.name = name
        self.existing_sim_id = existing_sim_id
        super().__init__(
            f"Simulation '{name}' already exists in project '{project}' "
            f"(existing sim_id {short_id(existing_sim_id)}). "
            f"Use on_collision='replace' or 'version' to proceed."
        )


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of :meth:`SimulationCatalog.register_simulation`.

    Attributes
    ----------
    sim_id
        UUID of the newly registered simulation.
    name
        Final name assigned to the simulation (may differ from the requested
        name when ``on_collision='version'`` auto-suffixes it).
    zarr
        The freshly created :class:`SimulationZarr`, or ``None`` when mesh
        dimensions are not yet known at registration time.
    replaced_sim_id
        UUID of a previously named simulation whose name was cleared by a
        soft-replace. ``None`` when no collision occurred.
    """

    sim_id: str
    name: str | None
    zarr: SimulationZarr | None
    replaced_sim_id: str | None


def _sha256_streaming(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 of a file by reading it in fixed-size chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _next_available_version(
    db: duckdb.DuckDBPyConnection,
    project: str,
    base_name: str,
) -> str:
    """Return ``base_name.v{n}`` where ``n`` is the smallest free integer ≥ 2."""
    rows = db.execute(
        "SELECT name FROM simulations WHERE project = ? AND (name = ? OR name LIKE ?)",
        [project, base_name, base_name + ".v%"],
    ).fetchall()
    existing = {r[0] for r in rows}
    n = 2
    while f"{base_name}.v{n}" in existing:
        n += 1
    return f"{base_name}.v{n}"


def _coerce_timestamp(value: Any) -> Any:
    """Return a value suitable for a ``TIMESTAMPTZ`` column.

    Accepts ``None``, pandas ``Timestamp``, ``datetime``, or ISO string. Plain
    strings are validated and passed through; anything else is returned as-is
    for DuckDB to cast.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value
    return str(value)


def _python_value_type(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    return "string"


def _normalize_geometry_kind(geom_type: str | None) -> str | None:
    if not geom_type:
        return None
    mapping = {
        "Point": "point",
        "MultiPoint": "point",
        "LineString": "linestring",
        "MultiLineString": "linestring",
        "Polygon": "polygon",
        "MultiPolygon": "multipolygon",
    }
    return mapping.get(geom_type, "polygon")


def _epsg_from_crs(crs: str) -> int | None:
    """Best-effort extraction of an EPSG code from a CRS string."""
    if not crs:
        return None
    upper = crs.upper().strip()
    if upper.startswith("EPSG:"):
        try:
            return int(upper.split(":", 1)[1])
        except ValueError:
            return None
    try:
        from pyproj import CRS as _CRS

        return _CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


def _legacy_jsonl_row(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a calibration iteration row into the legacy JSONL shape.

    See ``hydromodpy.calibration.objective_mapping._parse_legacy_row`` for
    the consumer contract.
    """
    params = row.get("parameters") or {}
    metrics = row.get("metrics") or {}
    block_costs: dict[str, Any] = {}
    if isinstance(metrics, dict):
        nested = metrics.get("block_costs")
        if isinstance(nested, dict):
            block_costs = {str(k): v for k, v in nested.items()}
        else:
            block_costs = {str(k): v for k, v in metrics.items() if k != "block_costs"}
    status = row.get("status") or "unknown"
    failure_reason = None if status == "completed" else status
    return {
        "iteration_id": str(row.get("iteration", "")),
        "iteration": row.get("iteration"),
        "sim_id": row.get("sim_id"),
        "params_hash": row.get("params_hash"),
        "params_named": dict(params) if isinstance(params, dict) else {},
        "params_vector": ([float(v) for v in params.values()] if isinstance(params, dict) else []),
        "parameters": dict(params) if isinstance(params, dict) else {},
        "objective_total": row.get("objective_value"),
        "objective_value": row.get("objective_value"),
        "block_costs": block_costs,
        "metrics": metrics if metrics else None,
        "status": status,
        "failure_reason": failure_reason,
        "from_cache": bool(row.get("from_cache", False)),
        "duration_s": row.get("duration_s"),
    }


def _build_model_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Summarise per-parameter statistics across completed iterations."""
    import math

    by_param: dict[str, list[tuple[float, float | None]]] = {}
    for row in rows:
        if row.get("status") != "completed":
            continue
        params = row.get("parameters") or {}
        if not isinstance(params, dict):
            continue
        obj = row.get("objective_value")
        try:
            obj_value = float(obj) if obj is not None else None
        except (TypeError, ValueError):
            obj_value = None
        for name, value in params.items():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            by_param.setdefault(str(name), []).append((v, obj_value))

    out: dict[str, dict[str, float]] = {}
    for name, samples in by_param.items():
        values = [v for v, _ in samples]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        if n > 1:
            var = sum((v - mean) ** 2 for v in values) / (n - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        finite_obj = [(v, obj) for v, obj in samples if obj is not None and math.isfinite(obj)]
        if finite_obj:
            best = min(finite_obj, key=lambda pair: pair[1])[0]
        else:
            best = values[0]
        out[name] = {
            "min": min(values),
            "max": max(values),
            "mean": mean,
            "std": std,
            "best": best,
            "n": float(n),
        }
    return out


class SimulationCatalog:
    def __init__(self, workspace_path: Path | str) -> None:
        self._workspace = Path(workspace_path)
        self._workspace.mkdir(parents=True, exist_ok=True)

        self._db_path = self._workspace / "hydromodpy.duckdb"
        self._db = connect_with_retry(str(self._db_path))

        self._simulations_dir = self._workspace / "simulations"
        self._simulations_dir.mkdir(exist_ok=True)
        self._basename_cache: dict[str, str] = {}
        self._open_zarr_handles: list[SimulationZarr] = []

        ensure_schema(self._db, self._workspace)

    def _track_zarr_handle(self, handle: SimulationZarr) -> SimulationZarr:
        handle._on_close = self._untrack_zarr_handle
        self._open_zarr_handles.append(handle)
        return handle

    def _untrack_zarr_handle(self, handle: SimulationZarr) -> None:
        try:
            self._open_zarr_handles.remove(handle)
        except ValueError:
            pass

    def _close_open_zarr_handles(self) -> None:
        if not self._open_zarr_handles:
            return
        while self._open_zarr_handles:
            handle = self._open_zarr_handles.pop()
            try:
                handle.close()
            except Exception:
                logger.debug("Could not close SimulationZarr handle", exc_info=True)

    def _storage_basename_for(self, sim_id: str | UUID) -> str:
        """Return the on-disk basename for ``sim_id``.

        Reads ``simulations.storage_basename`` and falls back to the raw
        ``sim_id`` string when the column is ``NULL`` - the case for rows
        written before human-readable storage names were introduced.
        Such workspaces continue to work via the UUID fallback; new
        registrations populate the column going forward.
        """
        sid = str(sim_id)
        cached = self._basename_cache.get(sid)
        if cached is not None:
            return cached
        row = self._db.execute(
            "SELECT storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        basename = (row[0] if row else None) or sid
        self._basename_cache[sid] = basename
        return basename

    def _parquet_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the per-simulation Parquet directory (may not yet exist)."""
        return self._simulations_dir / f"{self._storage_basename_for(sim_id)}.parquet"

    def _parquet_path_for(self, sim_id: str | UUID, view_name: str) -> Path:
        """Return the Parquet file path for ``view_name`` under ``sim_id``."""
        return self._parquet_dir_for(sim_id) / f"{view_name}.parquet"

    def zarr_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr artefact path on disk (``.zarr.zip`` if packed)."""
        basename = self._storage_basename_for(sim_id)
        zipped = self._simulations_dir / f"{basename}.zarr.zip"
        if zipped.exists():
            return zipped
        return self._simulations_dir / f"{basename}.zarr"

    def parquet_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the per-simulation Parquet directory (public accessor)."""
        return self._parquet_dir_for(sim_id)

    def _refresh_parquet_view(self, view_name: str) -> None:
        """Refresh a Parquet-backed view DDL after files change on disk.

        This must run inside the catalog connection so the view picks up
        newly created or newly emptied per-sim Parquet files. Idempotent.
        """
        ensure_parquet_views(self._db, self._workspace)

    def _atomic_write_parquet(
        self,
        target: Path,
        insert_df: pd.DataFrame,
        select_sql: str,
        pk_cols: tuple[str, ...] | None = None,
    ) -> None:
        """Write ``insert_df`` into ``target`` atomically, via ``select_sql``.

        ``select_sql`` must be a ``SELECT ... FROM _hmp_insert`` that produces
        the target Parquet schema by casting each column. The DataFrame is
        registered on the DuckDB connection under the alias ``_hmp_insert``
        so the query can resolve it without relying on frame-based
        replacement scans (which look up the caller's locals).

        If ``target`` already exists, its rows are merged with the new ones
        via a ``QUALIFY ROW_NUMBER`` dedupe on ``pk_cols`` (last write wins),
        so the semantics match the old ``INSERT OR REPLACE`` behaviour.
        Writes go to a sibling ``.tmp`` file first and are promoted with
        ``os.replace`` so a crash mid-write never leaves a partial Parquet
        in the view.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        existing = target.exists()
        self._db.register("_hmp_insert", insert_df)
        try:
            if existing and pk_cols:
                existing_escaped = str(target).replace("'", "''")
                pk_list = ", ".join(pk_cols)
                merge_sql = (
                    f"WITH combined AS ("
                    f"  SELECT *, 0 AS _prio FROM read_parquet('{existing_escaped}')"
                    f"  UNION ALL BY NAME "
                    f"  SELECT *, 1 AS _prio FROM ({select_sql})"
                    f") "
                    f"SELECT * EXCLUDE _prio FROM combined "
                    f"QUALIFY ROW_NUMBER() OVER "
                    f"(PARTITION BY {pk_list} ORDER BY _prio DESC) = 1"
                )
                copy_sql = f"COPY ({merge_sql}) TO '{tmp}' (FORMAT PARQUET)"
            else:
                copy_sql = f"COPY ({select_sql}) TO '{tmp}' (FORMAT PARQUET)"
            self._db.execute(copy_sql)
        finally:
            self._db.unregister("_hmp_insert")
        os.replace(tmp, target)
        if not existing:
            self._refresh_parquet_view(target.stem)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._db

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    @property
    def project_path(self) -> Path:
        return self._workspace

    # -- Registration --------------------------------------------------------

    @with_lock_retry()
    def register_simulation(
        self,
        sim_id: str | UUID,
        project: str,
        solver: str,
        *,
        name: str | None = None,
        on_collision: OnCollisionMode = "replace",
        solver_category: str | None = None,
        flow_regime: str | None = None,
        config: dict | None = None,
        config_snapshot: dict | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
        n_timesteps: int | None = None,
        cell_types: list[str] | None = None,
        bbox: list[float] | tuple[float, float, float, float] | None = None,
        crs: str | None = None,
        crs_epsg: int | None = None,
        period_start: Any = None,
        period_end: Any = None,
        time_unit: str | None = None,
        parent_sim_id: str | UUID | None = None,
        mesh_hash: str | None = None,
        mesh_type: str | None = None,
        mesh_topology: str | None = None,
        geographic_fingerprint: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        config_source: str | Path | None = None,
    ) -> RegistrationResult:
        sid = str(sim_id)
        replaced_sid: str | None = None
        final_name = name

        if name:
            existing = self._db.execute(
                "SELECT sim_id FROM simulations WHERE project = ? AND name = ?",
                [project, name],
            ).fetchone()
            if existing:
                existing_sid = str(existing[0])
                if on_collision == "fail":
                    raise DuplicateSimulationNameError(project, name, existing_sid)
                if on_collision == "replace":
                    self._db.execute(
                        "UPDATE simulations SET name = NULL WHERE sim_id = ?",
                        [existing_sid],
                    )
                    replaced_sid = existing_sid
                    logger.info(
                        "Reassigning name '%s' in project '%s' "
                        "(previous sim %s kept, name cleared)",
                        name,
                        project,
                        short_id(existing_sid),
                    )
                elif on_collision == "version":
                    final_name = _next_available_version(self._db, project, name)
                    logger.info(
                        "Auto-versioned '%s' → '%s' in project '%s'",
                        name,
                        final_name,
                        project,
                    )
                else:
                    raise ValueError(f"Unknown on_collision mode: '{on_collision}'")

        if solver_category is None:
            solver_category = _resolve_solver_category(solver)

        config_json = json.dumps(config) if config else None
        snapshot_source = config_snapshot if config_snapshot is not None else config
        snapshot_json = json.dumps(snapshot_source) if snapshot_source is not None else None
        config_hash = None
        if config:
            config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

        bbox_xmin = bbox_ymin = bbox_xmax = bbox_ymax = None
        if bbox is not None and len(bbox) == 4:
            bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax = (float(v) for v in bbox)

        crs_wkt = crs
        if crs_epsg is None and crs:
            crs_epsg = _epsg_from_crs(crs)

        topology = mesh_topology
        if topology is None and mesh_type in ("dis", "disv", "disu"):
            topology = mesh_type
        p_start = _coerce_timestamp(period_start)
        p_end = _coerce_timestamp(period_end)

        storage_basename = build_storage_basename(project, final_name, sid)
        zarr_path = f"simulations/{storage_basename}.zarr"
        parent_sid = str(parent_sim_id) if parent_sim_id else None
        config_source_str = str(config_source) if config_source is not None else None
        self._basename_cache[sid] = storage_basename

        self._db.execute(
            """INSERT INTO simulations
               (sim_id, name, project, solver, solver_category, flow_regime,
                n_cells, n_layers, n_timesteps,
                bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                crs_wkt, crs_epsg,
                period_start, period_end, time_unit,
                config_toml, config_snapshot, config_hash, config_source,
                zarr_path, storage_basename, parent_sim_id, mesh_hash, mesh_topology,
                geographic_fingerprint, tags, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                sid,
                final_name,
                project,
                solver,
                solver_category,
                flow_regime,
                n_cells,
                n_layers,
                n_timesteps,
                bbox_xmin,
                bbox_ymin,
                bbox_xmax,
                bbox_ymax,
                crs_wkt,
                crs_epsg,
                p_start,
                p_end,
                time_unit,
                config_json,
                snapshot_json,
                config_hash,
                config_source_str,
                zarr_path,
                storage_basename,
                parent_sid,
                mesh_hash,
                topology,
                geographic_fingerprint,
                tags,
                notes,
            ],
        )

        zarr_obj: SimulationZarr | None = None
        if n_cells is not None and n_layers is not None:
            zarr_abs = self._workspace / zarr_path
            zarr_obj = self._track_zarr_handle(
                SimulationZarr.create(
                    zarr_abs,
                    n_cells=n_cells,
                    n_layers=n_layers,
                    cell_types=cell_types,
                    geographic_fingerprint=geographic_fingerprint,
                )
            )
        return RegistrationResult(
            sim_id=sid,
            name=final_name,
            zarr=zarr_obj,
            replaced_sim_id=replaced_sid,
        )

    # -- Parameter writes ----------------------------------------------------

    @with_lock_retry()
    def write_parameters(
        self,
        sim_id: str | UUID,
        params: list[dict],
    ) -> None:
        sid = str(sim_id)
        for p in params:
            zone = p.get("zone_id")
            zone_val = GLOBAL_ZONE if zone is None else str(zone)
            self._db.execute(
                """INSERT INTO parameters
                   (sim_id, param_name, zone_id, value, unit, parameterization)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    sid,
                    p["param_name"],
                    zone_val,
                    p.get("value"),
                    p.get("unit"),
                    p.get("parameterization"),
                ],
            )

    # -- Timeseries ----------------------------------------------------------

    @with_lock_retry()
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
        # The timeseries.datetime column is TIMESTAMPTZ (WITH TIME ZONE).
        # Normalize the index to a single tz-aware representation (UTC) so
        # the Parquet file stores a deterministic timestamp regardless of
        # the session timezone the caller runs under.
        dt_values = pd.DatetimeIndex(ts.index)
        if dt_values.tz is None:
            dt_values = dt_values.tz_localize("UTC")
        else:
            dt_values = dt_values.tz_convert("UTC")
        insert_df = pd.DataFrame(
            {
                "sim_id": np.full(n, sid, dtype=object),
                "station_id": np.full(n, station_id, dtype=object),
                "variable": np.full(n, variable, dtype=object),
                "datetime": dt_values,
                "value": ts.values.astype("float64"),
                "unit": np.full(n, unit, dtype=object),
                "qflag": np.full(n, "simulated", dtype=object),
            }
        )
        select_sql = (
            "SELECT "
            "CAST(sim_id AS UUID) AS sim_id, "
            "CAST(station_id AS VARCHAR) AS station_id, "
            "CAST(variable AS VARCHAR) AS variable, "
            "CAST(datetime AS TIMESTAMPTZ) AS datetime, "
            "CAST(value AS DOUBLE) AS value, "
            "CAST(unit AS VARCHAR) AS unit, "
            "CAST(qflag AS VARCHAR) AS qflag "
            "FROM _hmp_insert"
        )
        target = self._parquet_path_for(sid, "timeseries")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "station_id", "variable", "datetime"),
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
        unit: str = "m3/s",
    ) -> None:
        # Single-row convenience wrapper over the batched method so both
        # entry points share a single Parquet write path.
        self.write_budgets(
            sim_id,
            [
                {
                    "timestep": timestep,
                    "zone_id": zone_id,
                    "component": component,
                    "flux_in": flux_in,
                    "flux_out": flux_out,
                    "unit": unit,
                }
            ],
        )

    @with_lock_retry()
    def write_budgets(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        if not records:
            return
        sid = str(sim_id)
        insert_df = pd.DataFrame(records)
        insert_df["sim_id"] = sid
        if "zone_id" not in insert_df.columns:
            insert_df["zone_id"] = GLOBAL_ZONE
        else:
            insert_df["zone_id"] = insert_df["zone_id"].fillna(GLOBAL_ZONE)
        if "unit" not in insert_df.columns:
            insert_df["unit"] = "m3/s"
        select_sql = (
            "SELECT "
            "CAST(sim_id AS UUID) AS sim_id, "
            "CAST(timestep AS INTEGER) AS timestep, "
            "CAST(zone_id AS VARCHAR) AS zone_id, "
            "CAST(component AS VARCHAR) AS component, "
            "CAST(flux_in AS DOUBLE) AS flux_in, "
            "CAST(flux_out AS DOUBLE) AS flux_out, "
            "CAST(unit AS VARCHAR) AS unit "
            "FROM _hmp_insert"
        )
        target = self._parquet_path_for(sid, "budgets")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "timestep", "zone_id", "component"),
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
        # Single-row convenience wrapper; see ``write_budget``.
        self.write_mass_balances(
            sim_id,
            [
                {
                    "timestep": timestep,
                    "total_in": total_in,
                    "total_out": total_out,
                    "storage_in": storage_in,
                    "storage_out": storage_out,
                    "percent_error": percent_error,
                }
            ],
        )

    @with_lock_retry()
    def write_mass_balances(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        if not records:
            return
        sid = str(sim_id)
        insert_df = pd.DataFrame(records)
        insert_df["sim_id"] = sid
        if "unit" not in insert_df.columns:
            insert_df["unit"] = "m3/s"
        if "storage_in" not in insert_df.columns:
            insert_df["storage_in"] = 0.0
        if "storage_out" not in insert_df.columns:
            insert_df["storage_out"] = 0.0
        select_sql = (
            "SELECT "
            "CAST(sim_id AS UUID) AS sim_id, "
            "CAST(timestep AS INTEGER) AS timestep, "
            "CAST(total_in AS DOUBLE) AS total_in, "
            "CAST(total_out AS DOUBLE) AS total_out, "
            "CAST(storage_in AS DOUBLE) AS storage_in, "
            "CAST(storage_out AS DOUBLE) AS storage_out, "
            "CAST(percent_error AS DOUBLE) AS percent_error, "
            "CAST(unit AS VARCHAR) AS unit "
            "FROM _hmp_insert"
        )
        target = self._parquet_path_for(sid, "mass_balance")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "timestep"),
        )

    # -- Metrics -------------------------------------------------------------

    @with_lock_retry()
    def write_metric(
        self,
        sim_id: str | UUID,
        station_id: str,
        metric_name: str,
        value: float,
        *,
        variable: str = "head",
    ) -> None:
        self._db.execute(
            """INSERT OR REPLACE INTO metrics
               (sim_id, station_id, variable, metric_name, value)
               VALUES (?, ?, ?, ?, ?)""",
            [str(sim_id), station_id, variable, metric_name, value],
        )

    # -- Provenance ----------------------------------------------------------

    @with_lock_retry()
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
        source_type_value = (
            source_type
            if source_type
            in (
                "http_api",
                "custom_file",
                "derived",
                "cache",
            )
            else "derived"
        )
        self._db.execute(
            """INSERT OR REPLACE INTO provenance
               (sim_id, variable, source_type, source_ref,
                period_start, period_end, payload_sha256, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id),
                variable,
                source_type_value,
                source_ref,
                _coerce_timestamp(period_start),
                _coerce_timestamp(period_end),
                fp["checksum"],
                int(np.prod(data.shape)),
                json.dumps(fp["stats"]),
            ],
        )

    record_provenance = write_provenance

    # -- Observation points --------------------------------------------------

    @with_lock_retry()
    def register_observation_points(
        self,
        sim_id: str | UUID,
        points: dict[str, tuple[float, float]],
        variable: str = "head",
        layer: int = 0,
    ) -> None:
        sid = str(sim_id)
        sz = self.open_zarr(sim_id)
        try:
            mesh = sz.root["mesh"]
            vertices = mesh["vertices"][:]
            connectivity = mesh["face_node_connectivity"][:]

            _ = variable
            mapping = point_in_cell(vertices, connectivity, points)
            for station_id, (x, y) in points.items():
                cell_id = mapping[station_id]
                self._db.execute(
                    """INSERT OR REPLACE INTO observation_points
                       (sim_id, station_id, x, y, cell_id, layer)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [sid, station_id, x, y, cell_id, layer],
                )
        finally:
            sz.close()

    # -- Tracked input files --------------------------------------------------

    @with_lock_retry()
    def register_tracked_files(
        self,
        sim_id: str | UUID,
        entries: list[Any],
    ) -> int:
        """Persist tracked-file records for a simulation.

        Each entry must expose ``role``, ``category``, ``original_path``,
        ``canonical_path``, and ``portable`` (as produced by
        :func:`hydromodpy.core.tracking.collect_input_files`). The SHA-256
        and size are computed here from the canonical path. Files that
        disappeared between walker-resolution and this call are skipped
        with a logger warning to keep the setup step non-fatal.
        """
        sid = str(sim_id)
        written = 0
        for entry in entries:
            canonical = Path(entry.canonical_path)
            if not canonical.is_file():
                logger.warning(
                    "Tracked input '%s' missing on disk, skipping: %s",
                    entry.role,
                    canonical,
                )
                continue
            sha = _sha256_streaming(canonical)
            size = canonical.stat().st_size
            self._db.execute(
                """INSERT OR REPLACE INTO tracked_files
                   (sim_id, role, category, original_path, canonical_path,
                    sha256, size_bytes, portable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    sid,
                    entry.role,
                    entry.category,
                    entry.original_path,
                    str(canonical),
                    sha,
                    int(size),
                    bool(entry.portable),
                ],
            )
            written += 1
        return written

    def list_tracked_files(self, sim_id: str | UUID) -> pd.DataFrame:
        return self._db.execute(
            """SELECT role, category, original_path, canonical_path,
                      sha256, size_bytes, portable
               FROM tracked_files WHERE sim_id = ?
               ORDER BY role, canonical_path""",
            [str(sim_id)],
        ).fetchdf()

    # -- Geographic features & metadata (sim-scoped in DuckDB) ----------------

    @with_lock_retry()
    def write_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
        gdf: gpd.GeoDataFrame,
        *,
        geoparquet_path: str | None = None,
    ) -> None:
        if gdf.empty:
            return
        from shapely.ops import unary_union

        union_geom = unary_union([g for g in gdf.geometry if g is not None and not g.is_empty])
        geom_kind = _normalize_geometry_kind(union_geom.geom_type)
        crs_str = str(gdf.crs) if gdf.crs else None
        properties = {
            "geojson": gdf.to_json(),
            "n_features": int(len(gdf)),
        }
        self._db.execute(
            "INSERT OR REPLACE INTO geographic_features "
            "(sim_id, feature_name, geometry_kind, crs_wkt, "
            " geoparquet_path, properties) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                str(sim_id),
                feature_name,
                geom_kind,
                crs_str,
                geoparquet_path,
                json.dumps(properties),
            ],
        )

    def read_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
    ) -> gpd.GeoDataFrame:
        import geopandas as gpd_mod

        row = self._db.execute(
            "SELECT properties, crs_wkt FROM geographic_features "
            "WHERE sim_id = ? AND feature_name = ?",
            [str(sim_id), feature_name],
        ).fetchone()
        if row is None:
            raise KeyError(f"Feature '{feature_name}' not found for sim '{sim_id}'")
        properties_json, crs = row
        if not properties_json:
            raise KeyError(f"No payload for feature '{feature_name}'")
        props = json.loads(properties_json) if isinstance(properties_json, str) else properties_json
        geojson_str = props.get("geojson") if isinstance(props, dict) else None
        if not geojson_str:
            raise KeyError(f"No GeoJSON data for feature '{feature_name}'")
        gdf = gpd_mod.read_file(geojson_str)
        if crs and gdf.crs is None:
            gdf = gdf.set_crs(crs)
        return gdf

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        rows = self._db.execute(
            "SELECT feature_name FROM geographic_features WHERE sim_id = ? ORDER BY feature_name",
            [str(sim_id)],
        ).fetchall()
        return [r[0] for r in rows]

    @with_lock_retry()
    def write_geographic_metadata(
        self,
        sim_id: str | UUID,
        metadata: dict[str, object],
    ) -> None:
        sid = str(sim_id)
        for key, value in metadata.items():
            value_type = _python_value_type(value)
            self._db.execute(
                "INSERT OR REPLACE INTO geographic_metadata "
                "(sim_id, key, value, value_type) "
                "VALUES (?, ?, ?, ?)",
                [sid, str(key), None if value is None else str(value), value_type],
            )

    def read_geographic_metadata(self, sim_id: str | UUID) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT key, value FROM geographic_metadata WHERE sim_id = ?",
            [str(sim_id)],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # -- Geographic rasters (sim-scoped in Zarr) -----------------------------

    def write_geographic_raster(
        self,
        sim_id: str | UUID,
        name: str,
        data: np.ndarray,
        *,
        transform: tuple[float, ...],
        crs: str,
        nodata: float = -99999.0,
    ) -> None:
        sz = self.open_zarr(sim_id)
        try:
            sz.write_geographic_raster(name, data, transform=transform, crs=crs, nodata=nodata)
        finally:
            sz.close()

    # -- Zarr access ---------------------------------------------------------

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        basename = self._storage_basename_for(sim_id)
        zarr_zip = self._simulations_dir / f"{basename}.zarr.zip"
        if zarr_zip.exists():
            return self._track_zarr_handle(SimulationZarr(zarr_zip))
        return self._track_zarr_handle(SimulationZarr(self._simulations_dir / f"{basename}.zarr"))

    def open_zarr_group(self, sim_id: str | UUID, *, mode: str = "r"):
        return self.open_zarr(sim_id).root

    # -- Field I/O (delegates to SimulationZarr) -----------------------------

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
        sz = self.open_zarr(sim_id)
        try:
            sz.write_field(variable, timestep, values, n_timesteps=n_timesteps, subgroup=subgroup)
        finally:
            sz.close()

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
    ) -> None:
        sz = self.open_zarr(sim_id)
        try:
            sz.write_mesh(
                vertices,
                face_node_connectivity,
                z_interfaces,
                layer_indices=layer_indices,
                source_cell_indices=source_cell_indices,
            )
        finally:
            sz.close()

    def query_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        sz = self.open_zarr(sim_id)
        try:
            return sz.read_field(variable, timestep, layer=layer)
        except KeyError:
            from hydromodpy.results.virtual_fields import compute_virtual_field

            result = compute_virtual_field(self, str(sim_id), variable, timestep)
            if result is not None:
                if layer is not None and result.ndim == 2:
                    return result[layer]
                return result
            raise KeyError(f"Variable '{variable}' not found for sim={sim_id}") from None
        finally:
            sz.close()

    # -- Tabular queries -----------------------------------------------------

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
    ) -> pd.Series:
        query = (
            "SELECT datetime, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [str(sim_id), station_id, variable]
        if period is not None:
            # Datetimes are stored as UTC-aware TIMESTAMPTZ; normalize the
            # caller's bounds to tz-aware UTC so the comparison is stable
            # regardless of DuckDB's session timezone.
            lo = pd.Timestamp(period[0])
            hi = pd.Timestamp(period[1])
            lo = lo.tz_localize("UTC") if lo.tz is None else lo.tz_convert("UTC")
            hi = hi.tz_localize("UTC") if hi.tz is None else hi.tz_convert("UTC")
            query += " AND datetime >= ? AND datetime <= ?"
            params.extend([lo.to_pydatetime(), hi.to_pydatetime()])
        query += " ORDER BY datetime"
        result = self._db.execute(query, params).fetchdf()
        if result.empty:
            raise KeyError(f"No timeseries for sim={sim_id}, station={station_id}, var={variable}")
        # Strip tz back to naive so the returned series aligns with
        # simulation-internal tz-naive time indexes.
        idx = pd.DatetimeIndex(result["datetime"])
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        return pd.Series(
            result["value"].values,
            index=idx,
            name=variable,
        )

    def query_budget(
        self,
        sim_id: str | UUID,
        zone_id: str | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
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
        return self._db.execute(
            "SELECT * FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [str(sim_id)],
        ).fetchdf()

    def get_provenance(
        self,
        sim_id: str | UUID,
        variable: str | None = None,
    ) -> pd.DataFrame:
        query = "SELECT * FROM provenance WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if variable is not None:
            query += " AND variable = ?"
            params.append(variable)
        return self._db.execute(query, params).fetchdf()

    def list_simulations(self, **filters) -> pd.DataFrame:
        """Return one DataFrame row per simulation matching ``filters``.

        ``order_by`` is an optional SQL ORDER BY clause (e.g. ``"created_at DESC"``).
        When omitted, rows are returned in DuckDB storage order - which is
        typically insertion order but not guaranteed by SQL. Callers that need
        the most recent run should pass ``order_by="created_at DESC"`` and
        read ``iloc[0]``.
        """
        order_by = filters.pop("order_by", None)
        query = "SELECT * FROM simulations"
        params: list = []
        if filters:
            clauses = []
            for key, val in filters.items():
                clauses.append(f"{key} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)
        if order_by:
            query += f" ORDER BY {order_by}"
        return self._db.execute(query, params).fetchdf()

    def export(
        self,
        sim_id: str | UUID,
        variable: str,
        fmt: str,
        path: Path | str,
        **kwargs,
    ) -> Path:
        sid = str(sim_id)
        path = Path(path)
        zarr_path = str(self.zarr_path_for(sim_id))

        if fmt == "netcdf":
            from hydromodpy.results.exporters.netcdf import export_netcdf

            variables = [v.strip() for v in variable.split(",")]
            return export_netcdf(zarr_path, sid, variables, path, **kwargs)
        elif fmt == "csv":
            from hydromodpy.results.exporters.csv import export_csv

            return export_csv(
                self._db,
                sid,
                path,
                variable=variable if variable != "*" else None,
                **kwargs,
            )
        elif fmt == "vtu":
            from hydromodpy.results.exporters.vtu import export_vtu

            timestep = kwargs.pop("timestep", 0)
            return export_vtu(zarr_path, sid, variable, timestep, path, **kwargs)
        elif fmt == "geotiff":
            from hydromodpy.results.exporters.geotiff import export_geotiff

            timestep = kwargs.pop("timestep", 0)
            return export_geotiff(zarr_path, sid, variable, timestep, path, **kwargs)
        elif fmt == "shapefile":
            from hydromodpy.results.exporters.shapefile import export_shapefile

            timestep = kwargs.pop("timestep", 0)
            return export_shapefile(zarr_path, sid, variable, timestep, path, **kwargs)
        else:
            raise ValueError(f"Unknown export format '{fmt}'")

    # -- Simulation discovery ------------------------------------------------

    @property
    def simulations(self) -> pd.DataFrame:
        return self._db.execute("SELECT * FROM simulations ORDER BY created_at DESC").fetchdf()

    # -- Calibration session inspection -------------------------------------

    @property
    def calibration_sessions(self) -> pd.DataFrame:
        """Return every calibration session row as a DataFrame."""
        return self._db.execute(
            "SELECT * FROM calibration_sessions ORDER BY started_at DESC"
        ).fetchdf()

    def calibration_iterations(self, session_id: str | UUID) -> pd.DataFrame:
        """Return the iteration history for one session as a DataFrame."""
        sid = UUID(str(session_id)) if len(str(session_id).replace("-", "")) == 32 else session_id
        return self._db.execute(
            """
            SELECT iteration, sim_id, params_hash, parameters,
                   objective_value, metrics, status, from_cache, duration_s
              FROM calibration_iterations
             WHERE session_id = ?
             ORDER BY iteration
            """,
            [sid],
        ).fetchdf()

    def export_calibration_session(
        self,
        session_id: str | UUID,
        out_dir: Path | str,
    ) -> Path:
        """Export one calibration session to the legacy JSONL + manifest shape.

        Writes ``iteration_history.jsonl`` (one JSON per row) plus
        ``session_manifest.json`` under ``out_dir``. Returns ``out_dir``.

        The JSONL uses the legacy keys consumed by
        ``hydromodpy.calibration.objective_mapping`` so that benchmark
        plotting tools keep working unchanged. Mapping from the catalog
        schema:

        - ``iteration_id`` <- ``iteration`` (stringified)
        - ``params_named`` <- ``parameters``
        - ``params_vector`` <- ordered values of ``parameters``
        - ``objective_total`` <- ``objective_value``
        - ``block_costs`` <- ``metrics["block_costs"]`` if present in
          ``persist_iteration_detail="full"`` mode, otherwise the flat
          ``metrics`` dict (component-only summary)
        - ``failure_reason`` <- ``status`` when not ``completed``

        When the session config has ``persist_model_distribution=True``,
        a ``model_distribution.json`` file is also produced, summarising
        each parameter across completed iterations.
        """
        import json

        from hydromodpy.calibration.persistence import CalibrationPersistence

        out = Path(out_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)

        sid_str = str(session_id)
        sid = UUID(sid_str) if len(sid_str.replace("-", "")) == 32 else sid_str

        session_row = self._db.execute(
            """
            SELECT session_id, project, method, objective_name,
                   n_iterations, config, started_at, ended_at, status,
                   best_sim_id, best_objective, duration_s
              FROM calibration_sessions
             WHERE session_id = ?
            """,
            [sid],
        ).fetchone()
        if session_row is None:
            raise ValueError(f"Unknown calibration session {session_id!r}")
        manifest_keys = (
            "session_id",
            "project",
            "method",
            "objective_name",
            "n_iterations",
            "config",
            "started_at",
            "ended_at",
            "status",
            "best_sim_id",
            "best_objective",
            "duration_s",
        )
        manifest: dict[str, Any] = {}
        config_payload: dict[str, Any] | None = None
        for key, value in zip(manifest_keys, session_row, strict=True):
            if key in {"session_id", "best_sim_id"}:
                manifest[key] = None if value is None else str(value)
            elif key == "config":
                if isinstance(value, str) and value:
                    try:
                        decoded = json.loads(value)
                    except json.JSONDecodeError:
                        manifest[key] = value
                    else:
                        manifest[key] = decoded
                        if isinstance(decoded, dict):
                            config_payload = decoded
                else:
                    manifest[key] = value
                    if isinstance(value, dict):
                        config_payload = value
            else:
                manifest[key] = value
        manifest_path = out / "session_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, default=str, indent=2) + "\n",
            encoding="utf-8",
        )

        rows = CalibrationPersistence(self).load_iterations(str(session_id))
        jsonl_path = out / "iteration_history.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(_legacy_jsonl_row(row), default=str) + "\n")

        if config_payload and bool(config_payload.get("persist_model_distribution")):
            distribution = _build_model_distribution(rows)
            (out / "model_distribution.json").write_text(
                json.dumps(distribution, default=str, indent=2) + "\n",
                encoding="utf-8",
            )

        return out

    def resolve(
        self,
        ref: str | UUID,
        *,
        project: str | None = None,
    ) -> str:
        """Resolve a user reference to a simulation UUID.

        Accepts three forms, tried in order:

        1. Full UUID (with dashes, 36 chars).
        2. UUID prefix of ≥ 4 hex characters (no dashes). Must match a single
           simulation globally; raises :class:`AmbiguousReferenceError`
           otherwise.
        3. Exact ``name`` within ``project`` - requires the ``project``
           keyword.

        Raises :class:`SimulationNotFoundError` when nothing matches.
        """
        ref_s = str(ref).strip()
        if not ref_s:
            raise SimulationNotFoundError("Empty reference")

        if _UUID_FULL_RE.match(ref_s):
            row = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
                [ref_s.lower()],
            ).fetchone()
            if row:
                return str(row[0])

        ref_nodash = ref_s.replace("-", "").lower()
        if _HEX_RE.match(ref_nodash) and len(ref_nodash) >= _MIN_PREFIX_LEN:
            rows = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR), name FROM simulations "
                "WHERE REPLACE(CAST(sim_id AS VARCHAR), '-', '') LIKE ? || '%'",
                [ref_nodash],
            ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), r[1]) for r in rows],
                )

        if project is not None:
            row = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE project = ? AND name = ?",
                [project, ref_s],
            ).fetchone()
            if row:
                return str(row[0])
        else:
            rows = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR), project FROM simulations WHERE name = ?",
                [ref_s],
            ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), f"{ref_s} (project={r[1]})") for r in rows],
                )

        where = f"'{ref_s}'"
        context = f" in project '{project}'" if project else ""
        raise SimulationNotFoundError(
            f"Reference {where} not found{context}. "
            "Try `hmp list <project>` or `catalog.simulations` to see known runs."
        )

    def __getitem__(self, ref: str | UUID) -> Run:
        from hydromodpy.results.run import Run

        sid = self.resolve(ref)
        return Run(sid, self)

    def find(self, **filters) -> SimulationGroup:
        from hydromodpy.results.simulation_group import SimulationGroup

        query = "SELECT DISTINCT s.sim_id FROM simulations s"
        joins: list[str] = []
        clauses: list[str] = []
        # SQL binds positional placeholders in the order they appear in the
        # query text (JOINs before WHEREs), so keep the two bind lists separate
        # instead of one ordered by filter-insertion.
        join_params: list = []
        clause_params: list = []

        for key, val in filters.items():
            if key == "tags":
                clauses.append("list_contains(s.tags, ?)")
                clause_params.append(val)
            elif key.endswith("_gt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value > ?")
                clause_params.append(val)
            elif key.endswith("_lt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value < ?")
                clause_params.append(val)
            elif key.endswith("_gte"):
                metric = key[:-4]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value >= ?")
                clause_params.append(val)
            elif key == "crs":
                clauses.append("s.crs_wkt = ?")
                clause_params.append(val)
            elif key in (
                "project",
                "solver",
                "solver_category",
                "flow_regime",
                "status",
                "name",
                "crs_wkt",
                "mesh_topology",
                "geographic_fingerprint",
            ):
                clauses.append(f"s.{key} = ?")
                clause_params.append(val)
            else:
                raise ValueError(f"Unknown filter: '{key}'")

        if joins:
            query += " " + " ".join(joins)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.created_at DESC"

        rows = self._db.execute(query, join_params + clause_params).fetchall()
        sim_ids = [str(r[0]) for r in rows]
        return SimulationGroup(sim_ids, self)

    def latest(self, project: str) -> Run:
        from hydromodpy.results.run import Run

        row = self._db.execute(
            "SELECT sim_id FROM simulations "
            "WHERE project = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1",
            [project],
        ).fetchone()
        if row is None:
            raise KeyError(f"No completed simulation for project '{project}'")
        return Run(str(row[0]), self)

    def best(self, project: str, metric: str = "nse") -> Run:
        from hydromodpy.results.run import Run

        row = self._db.execute(
            "SELECT s.sim_id FROM simulations s "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND s.status = 'completed' "
            "AND m.metric_name = ? "
            "ORDER BY m.value DESC LIMIT 1",
            [project, metric],
        ).fetchone()
        if row is None:
            raise KeyError(
                f"No completed simulation with metric '{metric}' for project '{project}'"
            )
        return Run(str(row[0]), self)

    def sql(self, query: str, params: list | None = None) -> pd.DataFrame:
        if params:
            return self._db.execute(query, params).fetchdf()
        return self._db.execute(query).fetchdf()

    def cleanup(
        self,
        *,
        status: str | None = None,
        older_than: str | None = None,
    ) -> int:
        query = "SELECT sim_id FROM simulations WHERE 1=1"
        params: list = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if older_than is not None:
            query += " AND created_at < ?"
            params.append(older_than)

        rows = self._db.execute(query, params).fetchall()
        for (sid,) in rows:
            self.delete(str(sid))
        return len(rows)

    # -- Import / export -----------------------------------------------------

    def export_package(
        self,
        sim_id: str | UUID,
        output_path: Path | str,
    ) -> Path:
        """Export a simulation as a portable ``.hmp`` archive (tar.zst).

        Returns the path to the produced ``.hmp`` file.
        """
        from hydromodpy.results.exporters.hmp_package import (
            export_hmp_package,
        )

        return export_hmp_package(self, sim_id, output_path)

    def import_package(
        self,
        package_path: Path | str,
        *,
        force: bool = False,
        as_project: str | None = None,
        dematerialise_inputs: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Import a ``.hmp`` archive into this workspace.

        SHA-256 checksums in the archive manifest are verified before
        any catalog mutation. ``as_project`` overrides the project
        column on import. ``dematerialise_inputs`` copies the bundled
        inputs into ``<workspace>/data/<role>/`` and rewrites the stored
        config paths to point at the new locations.
        """
        from hydromodpy.results.exporters.hmp_package import (
            import_hmp_package,
        )

        return import_hmp_package(
            self,
            package_path,
            force=force,
            as_project=as_project,
            dematerialise_inputs=dematerialise_inputs,
            dry_run=dry_run,
        )

    # -- Lifecycle -----------------------------------------------------------

    @with_lock_retry()
    def finalize(
        self,
        sim_id: str | UUID,
        status: str = "completed",
        duration_s: float | None = None,
    ) -> None:
        sid = str(sim_id)
        self._db.execute(
            "UPDATE simulations SET status = ?, duration_s = ? WHERE sim_id = ?",
            [status, duration_s, sid],
        )

        if status == "completed":
            basename = self._storage_basename_for(sid)
            zarr_dir = self._simulations_dir / f"{basename}.zarr"
            if zarr_dir.is_dir():
                try:
                    self._close_open_zarr_handles()
                    sz = SimulationZarr(zarr_dir)
                    try:
                        sz.consolidate_metadata()
                        zip_path = sz.pack_to_zip()
                        rel = f"simulations/{zip_path.name}"
                        self._db.execute(
                            "UPDATE simulations SET zarr_path = ? WHERE sim_id = ?",
                            [rel, sid],
                        )
                    finally:
                        sz.close()
                except Exception:
                    logger.debug("Could not pack zarr to zip for sim %s", sid)

    @with_lock_retry()
    def delete(self, sim_id: str | UUID) -> None:
        sid = str(sim_id)

        row = self._db.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        # Resolve artefact paths while the row still exists so basename lookup
        # works; clearing the cache and deleting the row first would push
        # resolution onto the raw-UUID fallback and miss the real folder.
        parquet_dir = self._parquet_dir_for(sid)
        self._basename_cache.pop(sid, None)

        for table in PER_SIM_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._db.execute(
            "DELETE FROM calibration_iterations WHERE sim_id = ?",
            [sid],
        )
        self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

        if parquet_dir.is_dir():
            shutil.rmtree(parquet_dir, ignore_errors=True)
            # Refresh views so a workspace whose last per-sim Parquet file
            # was just removed drops back to the empty-typed view form.
            ensure_parquet_views(self._db, self._workspace)

        if row and row[0]:
            zarr_abs = self._workspace / row[0]
            if zarr_abs.is_file():
                zarr_abs.unlink(missing_ok=True)
            elif zarr_abs.is_dir():
                shutil.rmtree(zarr_abs, ignore_errors=True)

    def close(self) -> None:
        self._close_open_zarr_handles()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        try:
            count = self._db.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        except Exception:
            count = "?"
        return f"SimulationCatalog(workspace={str(self._workspace)!r}, simulations={count})"

    def _repr_html_(self) -> str:
        try:
            count = self._db.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) FROM simulations"
            ).fetchone()
            total, ok, failed = count
            projects = [
                str(r[0])
                for r in self._db.execute("SELECT DISTINCT project FROM simulations").fetchall()
            ]
        except Exception:
            total, ok, failed, projects = 0, 0, 0, []
        projects_str = ", ".join(sorted(projects)) if projects else "&mdash;"
        rows = [
            ("workspace", f"<code>{self._workspace}</code>"),
            ("simulations", f"{total or 0} ({ok or 0} success, {failed or 0} failed)"),
            ("projects", projects_str),
        ]
        body = "".join(
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>" for k, v in rows
        )
        return (
            "<div><b>SimulationCatalog</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
