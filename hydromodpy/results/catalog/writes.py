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
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
import pandas as pd

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results.array_fingerprint import fingerprint
from hydromodpy.results.catalog.storage_paths import sanitize_segment
from hydromodpy.results.catalog_schema import GLOBAL_ZONE, ensure_parquet_views
from hydromodpy.results.spatial_index import point_in_cell

PARQUET_SCHEMA_VERSION = "v1.0"

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)


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


def _epsg_from_crs(crs: str | None) -> int | None:
    if not crs:
        return None
    upper = str(crs).upper().strip()
    if upper.startswith("EPSG:"):
        try:
            return int(upper.split(":", 1)[1])
        except ValueError:
            return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


def _json_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class WritesMixin:
    """Mutating operations for :class:`SimulationCatalog`.

    Relies on attributes provided by the facade: ``self._db``,
    ``self._workspace``, ``self._paths`` (StoragePathResolver),
    ``self._persistence`` (PersistenceConfig), and ``self.open_zarr``
    (LifecycleMixin). Each write method early-returns when the relevant
    ``PersistenceConfig`` flag is False, so a single switch governs all
    sinks (DuckDB, Parquet, Zarr).
    """

    @with_lock_retry()
    def write_parameters(
        self,
        sim_id: str | UUID,
        params: list[dict],
    ) -> None:
        if not self._persistence.save_catalog:
            return
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
        qflag: str = "simulated",
    ) -> None:
        if not self._persistence.save_parquet:
            return
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
                "qflag": np.full(n, qflag, dtype=object),
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
            kv_metadata=self._kv_metadata_for_sim(sid),
        )

    @with_lock_retry()
    def write_observations(
        self,
        station_id: str,
        variable_type: str,
        ts: pd.Series,
        unit: str = "",
        quality: str | None = None,
    ) -> None:
        n = len(ts)
        if n == 0:
            return
        dt_values = pd.DatetimeIndex(ts.index)
        if dt_values.tz is None:
            dt_values = dt_values.tz_localize("UTC")
        else:
            dt_values = dt_values.tz_convert("UTC")
        insert_df = pd.DataFrame(
            {
                "station_id": np.full(n, station_id, dtype=object),
                "variable_type": np.full(n, variable_type, dtype=object),
                "datetime": dt_values,
                "value": ts.values.astype("float64"),
                "unit": np.full(n, unit, dtype=object),
                "quality": np.full(n, quality, dtype=object),
            }
        )
        self._db.register("_hmp_insert", insert_df)
        try:
            self._db.execute(
                """
                DELETE FROM observations
                WHERE station_id = ?
                  AND variable_type = ?
                  AND datetime IN (
                      SELECT CAST(datetime AS TIMESTAMPTZ) FROM _hmp_insert
                  )
                """,
                [station_id, variable_type],
            )
            self._db.execute(
                """
                INSERT INTO observations
                    (station_id, variable_type, datetime, value, unit, quality)
                SELECT
                    CAST(station_id AS VARCHAR),
                    CAST(variable_type AS VARCHAR),
                    CAST(datetime AS TIMESTAMPTZ),
                    CAST(value AS DOUBLE),
                    CAST(unit AS VARCHAR),
                    CAST(quality AS VARCHAR)
                FROM _hmp_insert
                """
            )
        finally:
            self._db.unregister("_hmp_insert")

    @with_lock_retry()
    def write_station(
        self,
        station_id: str,
        variable_type: str,
        *,
        name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        elevation: float | None = None,
        source: str | None = None,
        first_valid: Any = None,
        last_valid: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        self._db.execute(
            """
            INSERT INTO stations
                (station_id, variable_type, name, latitude, longitude, elevation,
                 source, first_valid, last_valid, metadata, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            ON CONFLICT (station_id, variable_type) DO UPDATE SET
                name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                elevation = EXCLUDED.elevation,
                source = EXCLUDED.source,
                first_valid = EXCLUDED.first_valid,
                last_valid = EXCLUDED.last_valid,
                metadata = EXCLUDED.metadata,
                active = TRUE
            """,
            [
                station_id,
                variable_type,
                name,
                latitude,
                longitude,
                elevation,
                source,
                _coerce_timestamp(first_valid),
                _coerce_timestamp(last_valid),
                json.dumps(metadata or {}),
            ],
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
        if not self._persistence.save_parquet:
            return
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
            kv_metadata=self._kv_metadata_for_sim(sid),
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
        if not self._persistence.save_parquet:
            return
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
            kv_metadata=self._kv_metadata_for_sim(sid),
        )

    @with_lock_retry()
    def write_run_environment(
        self,
        sim_id: str | UUID,
        *,
        project_root: Path | str | None = None,
        mf6_binary_path: Path | str | None = None,
        rng_seed: int | None = None,
    ) -> None:
        """Capture and persist the host environment snapshot for ``sim_id``.

        Idempotent: re-calling overwrites the previous row. Heavy collection
        steps (``pip list``, ``cpuinfo``) tolerate failures and fall back
        to partial values rather than raising.

        ``rng_seed`` is the master seed driving ``RngManager``. Pass the
        same value to reproduce stochastic stages (mesh sampling, random
        forcing, calibration draws) from the catalog snapshot.
        """
        if not self._persistence.save_catalog:
            return
        from hydromodpy.results.run_environment import capture_environment

        snap = capture_environment(
            project_root=project_root,
            mf6_binary_path=mf6_binary_path,
        )
        self._db.execute(
            """INSERT OR REPLACE INTO runs_environment
               (sim_id, python_version, hydromodpy_version, platform,
                hostname, user_name, cpu_info, memory_gb,
                git_commit, project_git_commit, mf6_binary_sha256,
                mf6_version_text, conda_env_hash, env_packages, rng_seed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id),
                snap.get("python_version"),
                snap.get("hydromodpy_version"),
                snap.get("platform"),
                snap.get("hostname"),
                snap.get("user_name"),
                json.dumps(snap.get("cpu_info") or {}),
                snap.get("memory_gb"),
                snap.get("git_commit"),
                snap.get("project_git_commit"),
                snap.get("mf6_binary_sha256"),
                snap.get("mf6_version_text"),
                snap.get("conda_env_hash"),
                json.dumps(snap.get("env_packages") or []),
                None if rng_seed is None else int(rng_seed),
            ],
        )

    @with_lock_retry()
    def write_scientific_objective(
        self,
        sim_id: str | UUID,
        objective: str,
        *,
        description: str | None = None,
        contact_email: str | None = None,
        doi: str | None = None,
        study_area_name: str | None = None,
        outlet_x: float | None = None,
        outlet_y: float | None = None,
    ) -> None:
        """Record the scientific objective and related metadata for ``sim_id``.

        ``objective`` is the canonical stratification key used by
        :meth:`SimulationCatalog.training_split`. The other fields are free
        annotations for citation, geographic context, and contact lookup.
        """
        if not self._persistence.save_catalog:
            return
        if not objective or not str(objective).strip():
            raise ValueError("scientific_objective must be a non-empty string")
        self._db.execute(
            """UPDATE simulations SET
                   scientific_objective = ?,
                   description = COALESCE(?, description),
                   contact_email = COALESCE(?, contact_email),
                   doi = COALESCE(?, doi),
                   study_area_name = COALESCE(?, study_area_name),
                   outlet_x = COALESCE(?, outlet_x),
                   outlet_y = COALESCE(?, outlet_y)
               WHERE sim_id = ?""",
            [
                str(objective),
                description,
                contact_email,
                doi,
                study_area_name,
                outlet_x,
                outlet_y,
                str(sim_id),
            ],
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
        n_samples: int | None = None,
        period_start: Any | None = None,
        period_end: Any | None = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        self._db.execute(
            """INSERT OR REPLACE INTO metrics
               (sim_id, station_id, variable, metric_name, value,
                n_samples, period_start, period_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id),
                station_id,
                variable,
                metric_name,
                value,
                n_samples,
                period_start,
                period_end,
            ],
        )
        if self._persistence.save_parquet:
            insert_df = pd.DataFrame(
                [
                    {
                        "sim_id": str(sim_id),
                        "station_id": station_id,
                        "variable": variable,
                        "metric_name": metric_name,
                        "value": value,
                        "n_samples": n_samples,
                        "period_start": _coerce_timestamp(period_start),
                        "period_end": _coerce_timestamp(period_end),
                    }
                ]
            )
            select_sql = (
                "SELECT "
                "CAST(sim_id AS UUID) AS sim_id, "
                "CAST(station_id AS VARCHAR) AS station_id, "
                "CAST(variable AS VARCHAR) AS variable, "
                "CAST(metric_name AS VARCHAR) AS metric_name, "
                "CAST(value AS DOUBLE) AS value, "
                "CAST(n_samples AS INTEGER) AS n_samples, "
                "CAST(period_start AS TIMESTAMPTZ) AS period_start, "
                "CAST(period_end AS TIMESTAMPTZ) AS period_end "
                "FROM _hmp_insert"
            )
            self._atomic_write_parquet(
                self._paths.parquet_path_for(str(sim_id), "metrics"),
                insert_df,
                select_sql,
                pk_cols=("sim_id", "station_id", "variable", "metric_name"),
                kv_metadata=self._kv_metadata_for_sim(str(sim_id)),
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
        source_sha256: str | None = None,
        loader_name: str | None = None,
        loader_version: str | None = None,
        fetched_at: Any = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        fp = fingerprint(data)
        allowed_source_types = (
            "http_api",
            "custom_file",
            "data_manager",
            "derived",
            "cache",
        )
        if source_type not in allowed_source_types:
            raise ValueError(
                f"Unknown provenance source_type {source_type!r}. "
                f"Expected one of {allowed_source_types}."
            )
        payload = [
            str(sim_id),
            variable,
            source_type,
            source_ref,
            source_sha256,
            loader_name,
            loader_version,
            _coerce_timestamp(fetched_at),
            _coerce_timestamp(period_start),
            _coerce_timestamp(period_end),
            fp["checksum"],
            int(np.prod(data.shape)),
            json.dumps(fp["stats"]),
        ]
        self._db.execute(
            """INSERT OR REPLACE INTO provenance
               (sim_id, variable, source_type, source_ref,
                source_sha256, loader_name, loader_version, fetched_at,
                period_start, period_end, payload_sha256, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
        if self._persistence.save_parquet:
            insert_df = pd.DataFrame(
                [
                    {
                        "sim_id": payload[0],
                        "variable": payload[1],
                        "source_type": payload[2],
                        "source_ref": payload[3],
                        "source_sha256": payload[4],
                        "loader_name": payload[5],
                        "loader_version": payload[6],
                        "fetched_at": payload[7],
                        "period_start": payload[8],
                        "period_end": payload[9],
                        "payload_sha256": payload[10],
                        "n_records": payload[11],
                        "stats": payload[12],
                    }
                ]
            )
            select_sql = (
                "SELECT "
                "CAST(sim_id AS UUID) AS sim_id, "
                "CAST(variable AS VARCHAR) AS variable, "
                "CAST(source_type AS VARCHAR) AS source_type, "
                "CAST(source_ref AS VARCHAR) AS source_ref, "
                "CAST(source_sha256 AS VARCHAR) AS source_sha256, "
                "CAST(loader_name AS VARCHAR) AS loader_name, "
                "CAST(loader_version AS VARCHAR) AS loader_version, "
                "CAST(fetched_at AS TIMESTAMPTZ) AS fetched_at, "
                "CAST(period_start AS TIMESTAMPTZ) AS period_start, "
                "CAST(period_end AS TIMESTAMPTZ) AS period_end, "
                "CAST(payload_sha256 AS VARCHAR) AS payload_sha256, "
                "CAST(n_records AS BIGINT) AS n_records, "
                "CAST(stats AS JSON) AS stats "
                "FROM _hmp_insert"
            )
            self._atomic_write_parquet(
                self._paths.parquet_path_for(str(sim_id), "provenance"),
                insert_df,
                select_sql,
                pk_cols=("sim_id", "variable", "source_ref"),
                kv_metadata=self._kv_metadata_for_sim(str(sim_id)),
            )

    @with_lock_retry()
    def register_observation_points(
        self,
        sim_id: str | UUID,
        points: dict[str, tuple[float, float]],
        variable: str = "head",
        layer: int = 0,
        *,
        crs: str | None = None,
        crs_epsg: int | None = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        sid = str(sim_id)
        if crs is None or crs_epsg is None:
            row = self._db.execute(
                "SELECT crs_wkt, crs_epsg FROM simulations WHERE sim_id = ?",
                [sid],
            ).fetchone()
            if row is not None:
                crs = crs or row[0]
                crs_epsg = crs_epsg if crs_epsg is not None else row[1]
        if crs is None:
            raise ValueError("Observation point CRS is required.")
        if crs_epsg is None:
            crs_epsg = _epsg_from_crs(crs)
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
                       (sim_id, station_id, x, y, cell_id, layer, crs_wkt, crs_epsg)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [sid, station_id, x, y, cell_id, layer, str(crs), crs_epsg],
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
        if not self._persistence.save_catalog:
            return 0
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
        if not self._persistence.save_catalog:
            return
        if gdf.empty:
            return
        from shapely.ops import unary_union

        union_geom = unary_union([g for g in gdf.geometry if g is not None and not g.is_empty])
        geom_kind = _normalize_geometry_kind(union_geom.geom_type)
        crs_str = str(gdf.crs) if gdf.crs else None
        if crs_str is None:
            raise ValueError("Geographic feature CRS is required.")
        sid = str(sim_id)
        target = self._geographic_feature_parquet_path(
            sid,
            feature_name,
            geoparquet_path=geoparquet_path,
        )
        rel_path = (
            str(target.relative_to(self._workspace))
            if target.is_relative_to(self._workspace)
            else str(target)
        )
        self._write_geographic_feature_parquet(gdf, target)
        bounds = [float(value) for value in gdf.total_bounds]
        schema_payload = {
            "columns": [str(col) for col in gdf.columns if col != gdf.geometry.name],
            "geometry_kind": geom_kind,
            "crs": crs_str,
        }
        schema_hash = hashlib.sha256(
            json.dumps(schema_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        properties = {
            "n_features": int(len(gdf)),
            "bbox": bounds,
            "geometry_encoding": "WKB",
            "schema_sha256": schema_hash,
        }
        self._db.execute(
            "INSERT OR REPLACE INTO geographic_features "
            "(sim_id, feature_name, geometry_kind, crs_wkt, "
            " geoparquet_path, properties) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                sid,
                feature_name,
                geom_kind,
                crs_str,
                rel_path,
                json.dumps(properties),
            ],
        )

    def _geographic_feature_parquet_path(
        self,
        sim_id: str,
        feature_name: str,
        *,
        geoparquet_path: str | None,
    ) -> Path:
        if geoparquet_path:
            path = Path(geoparquet_path)
            return path if path.is_absolute() else self._workspace / path
        safe_name = sanitize_segment(feature_name)
        return self._paths.parquet_dir_for(sim_id) / f"geographic_{safe_name}.parquet"

    def _write_geographic_feature_parquet(self, gdf: gpd.GeoDataFrame, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        plain = gdf.drop(columns=[gdf.geometry.name]).copy()
        for column in plain.columns:
            plain[column] = plain[column].map(_json_scalar)
        plain["geometry_wkb"] = [
            None if geom is None or geom.is_empty else bytes(geom.wkb) for geom in gdf.geometry
        ]
        plain["geometry_type"] = [
            None if geom is None or geom.is_empty else str(geom.geom_type) for geom in gdf.geometry
        ]
        self._db.register("_hmp_geographic_feature", plain)
        try:
            tmp_sql = str(tmp).replace("'", "''")
            self._db.execute(
                f"COPY (SELECT * FROM _hmp_geographic_feature) TO '{tmp_sql}' (FORMAT PARQUET)"
            )
        finally:
            self._db.unregister("_hmp_geographic_feature")
        os.replace(tmp, target)

    @with_lock_retry()
    def write_geographic_metadata(
        self,
        sim_id: str | UUID,
        metadata: dict[str, object],
    ) -> None:
        if not self._persistence.save_catalog:
            return
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
        if not self._persistence.save_zarr:
            return
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
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_field(variable, timestep, values, n_timesteps=n_timesteps, subgroup=subgroup)
        finally:
            sz.close()

    def write_time(
        self,
        sim_id: str | UUID,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_time(values, epoch=epoch, calendar=calendar, units=units)
        finally:
            sz.close()

    def write_crs(
        self,
        sim_id: str | UUID,
        *,
        crs_wkt: str,
        grid_mapping_name: str = "latitude_longitude",
        epsg_code: int | None = None,
        semi_major_axis: float | None = None,
        inverse_flattening: float | None = None,
    ) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            sz.write_crs(
                crs_wkt=crs_wkt,
                grid_mapping_name=grid_mapping_name,
                epsg_code=epsg_code,
                semi_major_axis=semi_major_axis,
                inverse_flattening=inverse_flattening,
            )
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
        if not self._persistence.save_zarr:
            return
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

    def _kv_metadata_for_sim(self, sim_id: str) -> dict[str, str]:
        """Return Parquet KV metadata keys per the ML-access spec.

        Pulled from the ``simulations`` row plus the package version. Missing
        columns map to empty strings so the layout is stable across runs.
        """
        row = self._db.execute(
            "SELECT project, name, solver, config_hash, scientific_objective "
            "FROM simulations WHERE sim_id = ?",
            [sim_id],
        ).fetchone()
        project, name, solver, config_hash, objective = row or (None, None, None, None, None)
        return {
            "sim_id": sim_id,
            "project": str(project) if project is not None else "",
            "name": str(name) if name is not None else "",
            "solver": str(solver) if solver is not None else "",
            "config_hash": str(config_hash) if config_hash is not None else "",
            "hydromodpy_version": _HMP_VERSION,
            "schema_version": PARQUET_SCHEMA_VERSION,
            "written_at": datetime.now(UTC).isoformat(),
            "scientific_objective": str(objective) if objective is not None else "",
        }

    def _atomic_write_parquet(
        self,
        target: Path,
        insert_df: pd.DataFrame,
        select_sql: str,
        pk_cols: tuple[str, ...] | None = None,
        kv_metadata: dict[str, str] | None = None,
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
        kv_clause = _format_kv_clause(kv_metadata)
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
                copy_sql = f"COPY ({merge_sql}) TO '{tmp}' (FORMAT PARQUET{kv_clause})"
            else:
                copy_sql = f"COPY ({select_sql}) TO '{tmp}' (FORMAT PARQUET{kv_clause})"
            self._db.execute(copy_sql)
        finally:
            self._db.unregister("_hmp_insert")
        os.replace(tmp, target)
        if not existing:
            self._refresh_parquet_view(target.stem)


def _format_kv_clause(kv: dict[str, str] | None) -> str:
    """Render ``KV_METADATA {{...}}`` as a DuckDB ``COPY`` option suffix.

    Returns an empty string when ``kv`` is empty / None. Values must be
    plain strings; embedded single quotes are escaped by doubling them.
    """
    if not kv:
        return ""
    pairs = []
    for key, val in sorted(kv.items()):
        safe_val = str(val).replace("'", "''")
        pairs.append(f"{key}: '{safe_val}'")
    return f", KV_METADATA {{{', '.join(pairs)}}}"
