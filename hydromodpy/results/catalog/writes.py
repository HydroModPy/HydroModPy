"""Per-simulation write operations.

Every method that mutates a per-sim Parquet file or DuckDB row after the
simulation is registered: the ``write_*`` family, observation-point and
tracked-input registration, geographic metadata writes, and the shared
atomic-Parquet helper that drives them all. ``register_simulation`` lives
in :mod:`hydromodpy.results.catalog.registration`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
import pandas as pd

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.results.catalog_schema import GLOBAL_ZONE, ensure_parquet_views
from hydromodpy.results.provenance import fingerprint
from hydromodpy.results.spatial_index import point_in_cell

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)


def _sha256_streaming(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 of a file by reading it in fixed-size chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _coerce_timestamp(value: Any) -> Any:
    """Return a value suitable for a ``TIMESTAMPTZ`` column."""
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


class WritesMixin:
    """Mutating operations for :class:`SimulationCatalog`.

    Relies on attributes provided by the facade: ``self._db``,
    ``self._workspace``, ``self._paths`` (StoragePathResolver), and
    ``self.open_zarr`` (LifecycleMixin).
    """

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
        target = self._paths.parquet_path_for(sid, "timeseries")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "station_id", "variable", "datetime"),
        )

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
        target = self._paths.parquet_path_for(sid, "budgets")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "timestep", "zone_id", "component"),
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
        target = self._paths.parquet_path_for(sid, "mass_balance")
        self._atomic_write_parquet(
            target,
            insert_df,
            select_sql,
            pk_cols=("sim_id", "timestep"),
        )

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

    def _refresh_parquet_view(self, view_name: str) -> None:
        """Refresh a Parquet-backed view DDL after files change on disk.

        Idempotent. Writes go through this so newly created or emptied per-sim
        Parquet files are reflected in the workspace-wide view.
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
