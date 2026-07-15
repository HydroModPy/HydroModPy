"""Parquet write concern for :class:`Catalog`.

Per-simulation Parquet outputs: timeseries, observations, budgets,
mass balance, geographic features. Shared parquet plumbing
(``_write_parquet_records``, ``_kv_metadata_for_sim``,
``_refresh_parquet_view``) lives here too because every parquet writer
funnels through it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
import pandas as pd
import pyarrow as pa

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import encode_workspace_path as _encode_workspace_path
from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results.catalog.constants import GLOBAL_ZONE
from hydromodpy.results.catalog.parquet_views import ensure_parquet_views, view_name_for
from hydromodpy.results.catalog.storage_paths import sanitize_segment
from hydromodpy.results.catalog.writes_helpers import (
    _merge_with_existing,
    _normalize_geometry_kind,
    _table_from_columns,
    _table_from_records,
)
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.parquet_io import read_kv_metadata, write_table_atomic
from hydromodpy.results.storage.parquet_schemas import (
    BUDGETS_SCHEMA,
    MASS_BALANCE_SCHEMA,
    PARQUET_SCHEMA_VERSION,
    TIMESERIES_SCHEMA,
)

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)


class WritesMixinParquet:
    """Parquet-backed write operations.

    Relies on facade attributes ``self._backend``, ``self._db``,
    ``self._workspace``, ``self._paths`` and ``self._persistence``. Every
    method early-returns when the relevant ``PersistenceConfig`` flag is
    False so a single switch governs the Parquet sink.
    """

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
        """Append a single station/variable timeseries to ``timeseries.parquet``."""
        if not self._persistence.save_parquet:
            return
        if ts is None or len(ts) == 0:
            return
        sid = str(sim_id)
        dt_values = pd.DatetimeIndex(ts.index)
        if dt_values.tz is None:
            dt_values = dt_values.tz_localize("UTC")
        else:
            dt_values = dt_values.tz_convert("UTC")
        records = [
            {
                "sim_id": sid,
                "station_id": station_id,
                "variable": variable,
                "component": None,
                "timestep": idx,
                "time": dt,
                "value": float(val),
                "unit": unit,
                "qflag": qflag,
            }
            for idx, (dt, val) in enumerate(
                zip(dt_values.to_pydatetime(), ts.values.astype("float64"), strict=False)
            )
        ]
        self._write_parquet_records(
            target=self._paths.parquet_path_for(sid, "timeseries"),
            records=records,
            schema=TIMESERIES_SCHEMA,
            pk_cols=("sim_id", "station_id", "variable", "timestep"),
            sim_id=sid,
        )

    @with_lock_retry()
    def write_timeseries_batch(
        self,
        sim_id: str | UUID,
        records: Sequence[Mapping[str, Any]],
    ) -> None:
        """Write a batch of timeseries records to ``timeseries.parquet`` in one pass.

        ``records`` must use the column names of :data:`TIMESERIES_SCHEMA`:
        ``sim_id``, ``station_id``, ``variable``, ``component``, ``timestep``,
        ``time``, ``value``, ``unit``, ``qflag``. Missing keys default to
        ``None``. Compared to looping over :meth:`write_timeseries`, this entry
        point avoids the O(N**2) read/merge/rewrite pattern: the merge happens
        once against the existing file.
        """
        if not self._persistence.save_parquet:
            return
        if not records:
            return
        sid = str(sim_id)
        normalised: list[dict[str, Any]] = []
        for record in records:
            row = dict(record)
            row.setdefault("sim_id", sid)
            row.setdefault("component", None)
            row.setdefault("unit", "")
            row.setdefault("qflag", "simulated")
            normalised.append(row)
        self._write_parquet_records(
            target=self._paths.parquet_path_for(sid, "timeseries"),
            records=normalised,
            schema=TIMESERIES_SCHEMA,
            pk_cols=("sim_id", "station_id", "variable", "timestep"),
            sim_id=sid,
        )

    @with_lock_retry()
    def write_timeseries_columns(
        self,
        sim_id: str | UUID,
        columns: Mapping[str, Any],
    ) -> None:
        """Columnar fast path of :meth:`write_timeseries_batch`.

        ``columns`` maps :data:`TIMESERIES_SCHEMA` column names to equal-length
        per-row arrays; scalars broadcast and missing columns get the batch
        defaults. Building the Arrow table from arrays skips the per-record
        Python loop, which matters for multi-million-row solver series.
        """
        if not self._persistence.save_parquet:
            return
        if not columns:
            return
        sid = str(sim_id)
        table = _table_from_columns(
            columns,
            TIMESERIES_SCHEMA,
            defaults={"sim_id": sid, "unit": "", "qflag": "simulated"},
        )
        if table.num_rows == 0:
            return
        self._write_parquet_table(
            target=self._paths.parquet_path_for(sid, "timeseries"),
            new_table=table,
            pk_cols=("sim_id", "station_id", "variable", "timestep"),
            sim_id=sid,
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
        # port escape: DuckDB-specific register() to bind an in-memory DataFrame.
        self._db.register("_hmp_insert", insert_df)
        try:
            self._backend.execute(
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
            self._backend.execute(
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
            # port escape: DuckDB-specific unregister().
            self._db.unregister("_hmp_insert")

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
        normalised: list[dict[str, Any]] = []
        for r in records:
            row = dict(r)
            row.setdefault("sim_id", sid)
            zone = row.get("zone_id")
            if zone is None:
                row["zone_id"] = GLOBAL_ZONE
            else:
                row["zone_id"] = str(zone)
            row.setdefault("unit", "m3/s")
            row["timestep"] = int(row["timestep"])
            normalised.append(row)
        self._write_parquet_records(
            target=self._paths.parquet_path_for(sid, "budgets"),
            records=normalised,
            schema=BUDGETS_SCHEMA,
            pk_cols=("sim_id", "timestep", "zone_id", "component"),
            sim_id=sid,
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
        normalised: list[dict[str, Any]] = []
        for r in records:
            row = dict(r)
            row.setdefault("sim_id", sid)
            # 'water' is the GWF volume budget; GWT solute rows set quantity='solute'.
            row.setdefault("quantity", "water")
            row.setdefault("unit", "m3/s")
            row.setdefault("storage_in", 0.0)
            row.setdefault("storage_out", 0.0)
            row["timestep"] = int(row["timestep"])
            normalised.append(row)
        self._write_parquet_records(
            target=self._paths.parquet_path_for(sid, "mass_balance"),
            records=normalised,
            schema=MASS_BALANCE_SCHEMA,
            pk_cols=("sim_id", "timestep", "quantity"),
            sim_id=sid,
        )

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
        rel_path = _encode_workspace_path(self._workspace, target)
        write_geoparquet_atomic(gdf, target)
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
            "geoparquet_version": "1.1.0",
        }
        self._backend.execute(
            """INSERT INTO geographic_features
               (sim_id, feature_name, geometry_kind, crs_wkt,
                geoparquet_path, properties)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (sim_id, feature_name)
               DO UPDATE SET
                   geometry_kind = EXCLUDED.geometry_kind,
                   crs_wkt = EXCLUDED.crs_wkt,
                   geoparquet_path = EXCLUDED.geoparquet_path,
                   properties = EXCLUDED.properties""",
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
        import os as _os

        if geoparquet_path:
            path = Path(geoparquet_path)
            return path if path.is_absolute() else self._workspace / path
        safe_name = sanitize_segment(feature_name)
        target = (
            self._paths.parquet_dir_for(sim_id) / f"geographic_{safe_name}{PARQUET_FILE_SUFFIX}"
        )
        if _os.name == "nt" and len(str(target.resolve())) >= 240:
            digest = hashlib.sha1(safe_name.encode("utf-8")).hexdigest()[:16]
            return self._paths.parquet_dir_for(sim_id) / f"geographic_{digest}{PARQUET_FILE_SUFFIX}"
        return target

    def _refresh_parquet_view(self, view_name: str) -> None:
        """Refresh a Parquet-backed view DDL after files change on disk.

        Idempotent. Writes go through this so newly created or emptied per-sim
        Parquet files are reflected in the workspace-wide view.
        """
        ensure_parquet_views(self._db, self._simulations_dir)

    def _drop_parquet_view_before_write(self, view_name: str) -> None:
        """Drop a DuckDB Parquet view before replacing its backing file.

        DuckDB can keep ``read_parquet`` file handles open on Windows after a
        view has been materialized. Dropping the view before the atomic replace
        releases that handle; ``_refresh_parquet_view`` recreates it after the
        write.
        """

        existing_tables = {
            str(row[0])
            for row in self._db.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
            ).fetchall()
        }
        duckdb_view = view_name_for(view_name, existing_tables)
        escaped = duckdb_view.replace('"', '""')
        self._db.execute(f'DROP VIEW IF EXISTS "{escaped}"')

    def _kv_metadata_for_sim(self, sim_id: str) -> dict[str, str]:
        """Return Parquet KV metadata keys for ``sim_id``.

        Reads the simulation row plus a few catalog joins to enrich the file
        footer with ACDD-style geospatial/temporal coverage attributes. The
        returned ``written_at`` is *deterministic*: it is the simulation's
        ``ended_at`` (or ``created_at`` fallback), never ``datetime.now``, so a
        reproducible re-run lands on a byte-identical file.
        """
        row = self._backend.fetch_one(
            """SELECT s.project, s.name, sv.code, s.config_hash,
                      s.scientific_objective, s.bbox_xmin, s.bbox_ymin,
                      s.bbox_xmax, s.bbox_ymax, s.period_start, s.period_end,
                      s.crs_epsg, s.created_at, s.ended_at, s.doi
                 FROM simulations s
                 JOIN solvers sv ON s.solver_id = sv.id
                WHERE s.sim_id = ?""",
            [sim_id],
        )
        if row is None:
            return {
                "sim_id": sim_id,
                "hydromodpy_version": _HMP_VERSION,
                "hmp.schema_version": PARQUET_SCHEMA_VERSION,
                "Conventions": "CF-1.11",
                "license": "CC-BY-4.0",
                "written_at": "",
            }
        (
            project,
            name,
            solver,
            config_hash,
            objective,
            bb_xmin,
            bb_ymin,
            bb_xmax,
            bb_ymax,
            period_start,
            period_end,
            crs_epsg,
            created_at,
            ended_at,
            doi,
        ) = row
        written_at_source = ended_at if ended_at is not None else created_at
        kv: dict[str, str] = {
            "sim_id": sim_id,
            "project": "" if project is None else str(project),
            "name": "" if name is None else str(name),
            "solver": "" if solver is None else str(solver),
            "config_hash": "" if config_hash is None else str(config_hash),
            "hydromodpy_version": _HMP_VERSION,
            "hmp.schema_version": PARQUET_SCHEMA_VERSION,
            "Conventions": "CF-1.11",
            "license": "CC-BY-4.0",
            "scientific_objective": "" if objective is None else str(objective),
            "doi": "" if doi is None else str(doi),
            "written_at": "" if written_at_source is None else str(written_at_source),
        }
        if bb_xmin is not None and bb_xmax is not None:
            kv["geospatial_lon_min"] = str(bb_xmin)
            kv["geospatial_lon_max"] = str(bb_xmax)
        if bb_ymin is not None and bb_ymax is not None:
            kv["geospatial_lat_min"] = str(bb_ymin)
            kv["geospatial_lat_max"] = str(bb_ymax)
        if crs_epsg is not None:
            kv["geospatial_crs"] = f"EPSG:{int(crs_epsg)}"
        if period_start is not None:
            kv["time_coverage_start"] = str(period_start)
        if period_end is not None:
            kv["time_coverage_end"] = str(period_end)
        return kv

    def _write_parquet_records(
        self,
        *,
        target: Path,
        records: Sequence[Mapping[str, Any]],
        schema: pa.Schema,
        pk_cols: Sequence[str],
        sim_id: str,
    ) -> None:
        """Build a pyarrow Table from ``records`` and persist it atomically.

        If ``target`` already exists, a last-write-wins merge happens on
        ``pk_cols`` before the write. The new file replaces the previous one
        via :func:`os.replace` in :func:`write_table_atomic`.
        """
        defaults = {"sim_id": sim_id}
        new_table = _table_from_records(records, schema, defaults=defaults)
        self._write_parquet_table(
            target=target, new_table=new_table, pk_cols=pk_cols, sim_id=sim_id
        )

    def _write_parquet_table(
        self,
        *,
        target: Path,
        new_table: pa.Table,
        pk_cols: Sequence[str],
        sim_id: str,
    ) -> None:
        """Persist a prebuilt Arrow table atomically, merging with the target."""
        existing = target.exists()
        if existing:
            try:
                kv_existing = read_kv_metadata(target)
            except Exception:
                kv_existing = {}
            old_version = kv_existing.get("hmp.schema_version")
            if old_version and old_version != PARQUET_SCHEMA_VERSION:
                logger.warning(
                    "Parquet file %s carries schema_version=%s; rewriting as %s",
                    target,
                    old_version,
                    PARQUET_SCHEMA_VERSION,
                )
            merged = _merge_with_existing(target, new_table, pk_cols)
        else:
            merged = new_table
        kv = self._kv_metadata_for_sim(sim_id)
        self._drop_parquet_view_before_write(target.stem)
        write_table_atomic(merged, target, kv_metadata=kv, pk_cols=tuple(pk_cols))
        self._refresh_parquet_view(target.stem)


__all__ = ["WritesMixinParquet"]
