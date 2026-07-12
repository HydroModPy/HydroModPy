"""Read-side queries against the catalog.

Tabular ``query_*``, ``list_*``, ``read_geographic_*`` accessors plus a
DataFrame property over ``simulations`` and the ``export`` dispatch. All
methods are pure reads and never mutate DuckDB or the on-disk artefacts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.core.config_kit.export_spec import ExportSpec

# Filter columns that map to a real simulations.* column (no dim join).
_SIMULATION_DIRECT_FILTERS: frozenset[str] = frozenset(
    {
        "sim_id",
        "name",
        "project",
        "mesh_hash",
        "n_cells",
        "n_layers",
        "n_timesteps",
        "crs_wkt",
        "crs_epsg",
        "period_start",
        "period_end",
        "time_unit",
        "config_hash",
        "config_source",
        "parent_sim_id",
        "lineage_kind",
        "zarr_packed",
        "storage_basename",
        "geographic_fingerprint",
        "duration_s",
        "created_at",
        "updated_at",
        "scientific_objective",
        "study_area_name",
        "doi",
    }
)

# Filter columns resolved via dim-table JOINs.
_SIMULATION_DIM_FILTERS: dict[str, str] = {
    "solver": "sv.code",
    "solver_category": "sv.category",
    "flow_regime": "fr.code",
    "status": "st.code",
    "mesh_topology": "mt.code",
}

_SIMULATION_FILTER_COLUMNS: frozenset[str] = _SIMULATION_DIRECT_FILTERS | frozenset(
    _SIMULATION_DIM_FILTERS.keys()
)

_SIMULATION_ORDER_COLUMNS: frozenset[str] = _SIMULATION_FILTER_COLUMNS | frozenset(
    {
        "started_at",
        "ended_at",
        "bbox_xmin",
        "bbox_ymin",
        "bbox_xmax",
        "bbox_ymax",
    }
)
_ORDER_DIRECTIONS: frozenset[str] = frozenset({"ASC", "DESC"})


def _order_clause(order_by: str | tuple[str, str] | None) -> str | None:
    if order_by is None:
        return None
    if isinstance(order_by, tuple):
        column, direction = order_by
    else:
        parts = str(order_by).strip().split()
        if len(parts) == 1:
            column, direction = parts[0], "ASC"
        elif len(parts) == 2:
            column, direction = parts
        else:
            raise ValueError("order_by must be '<column>' or '<column> ASC|DESC'")
    if column not in _SIMULATION_ORDER_COLUMNS:
        raise ValueError(f"Unknown order_by column: {column!r}")
    direction = direction.upper()
    if direction not in _ORDER_DIRECTIONS:
        raise ValueError("order_by direction must be 'ASC' or 'DESC'")
    if column in _SIMULATION_DIM_FILTERS:
        return f"{_SIMULATION_DIM_FILTERS[column]} {direction}"
    return f"s.{column} {direction}"


_SIMULATIONS_VIEW_SELECT = (
    "SELECT s.*, "
    "sv.code AS solver, sv.category AS solver_category, "
    "st.code AS status, "
    "fr.code AS flow_regime, "
    "mt.code AS mesh_topology "
    "FROM simulations s "
    "JOIN solvers sv ON s.solver_id = sv.id "
    "JOIN statuses st ON s.status_id = st.id "
    "LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
    "LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id"
)


class ReadsMixin:
    """Read-only queries for :class:`Catalog`.

    Relies on attributes provided by the facade: ``self._backend``
    (CatalogBackend port), ``self._db`` (DuckDB connection, kept for
    exporters that take a raw cursor), and ``self._paths``
    (StoragePathResolver), plus ``self.open_zarr`` and
    ``self.zarr_path_for`` for field reads / exports.
    """

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

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
    ) -> pd.Series:
        from hydromodpy.results.time_alignment import normalize_period_bounds

        query = (
            "SELECT time, timestep, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [str(sim_id), station_id, variable]
        if period is not None:
            lo, hi, hi_inclusive = normalize_period_bounds(period)
            query += " AND time >= ? AND time " + ("<= ?" if hi_inclusive else "< ?")
            params.extend([lo, hi])
        query += " ORDER BY timestep"
        result = self._backend.query(query, params)
        if result.empty:
            raise KeyError(f"No timeseries for sim={sim_id}, station={station_id}, var={variable}")
        # Strip tz back to naive so the returned series aligns with
        # simulation-internal tz-naive time indexes.
        idx = pd.DatetimeIndex(result["time"])
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
        return self._backend.query(query, params)

    def query_mass_balance(self, sim_id: str | UUID) -> pd.DataFrame:
        return self._backend.query(
            "SELECT * FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [str(sim_id)],
        )

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
        return self._backend.query(query, params)

    def list_simulations(self, *, named_only: bool = False, **filters) -> pd.DataFrame:
        """Return one DataFrame row per simulation matching ``filters``.

        ``order_by`` accepts only whitelisted simulation columns, with an
        optional ``ASC`` or ``DESC`` direction. ``named_only=True`` drops the
        technical rows: runs whose name was cleared on a replace collision
        (``name IS NULL``) and effective-config snapshots (dotted names).
        """
        order_by = filters.pop("order_by", None)
        query = _SIMULATIONS_VIEW_SELECT
        params: list = []
        clauses: list[str] = []
        for key, val in filters.items():
            if key not in _SIMULATION_FILTER_COLUMNS:
                raise ValueError(f"Unknown simulation filter: {key!r}")
            if key in _SIMULATION_DIM_FILTERS:
                clauses.append(f"{_SIMULATION_DIM_FILTERS[key]} = ?")
            else:
                clauses.append(f"s.{key} = ?")
            params.append(val)
        if named_only:
            clauses.append("s.name IS NOT NULL")
            clauses.append("s.name NOT LIKE '.%'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        clause = _order_clause(order_by)
        if clause is not None:
            query += f" ORDER BY {clause}"
        return self._backend.query(query, params)

    def list_tracked_files(self, sim_id: str | UUID) -> pd.DataFrame:
        return self._backend.query(
            """SELECT role, category, original_path, canonical_path,
                      sha256, size_bytes, portable
               FROM tracked_files WHERE sim_id = ?
               ORDER BY role, canonical_path""",
            [str(sim_id)],
        )

    def read_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
    ) -> gpd.GeoDataFrame:
        """Read a per-simulation GeoParquet 1.1 feature via geopandas."""
        from hydromodpy.core.io.geoparquet import read_geoparquet

        row = self._backend.fetch_one(
            "SELECT geoparquet_path, properties, crs_wkt FROM geographic_features "
            "WHERE sim_id = ? AND feature_name = ?",
            [str(sim_id), feature_name],
        )
        if row is None:
            raise KeyError(f"Feature '{feature_name}' not found for sim '{sim_id}'")
        parquet_path, properties_json, _crs = row
        if not parquet_path:
            raise KeyError(f"No Parquet payload for feature '{feature_name}'")
        path = Path(parquet_path)
        if not path.is_absolute():
            path = self._workspace / path
        if not path.is_file():
            raise FileNotFoundError(path)
        gdf = read_geoparquet(path)
        if properties_json:
            props = (
                json.loads(properties_json) if isinstance(properties_json, str) else properties_json
            )
            if isinstance(props, dict) and props.get("geometry_encoding") != "WKB":
                raise ValueError(f"Unsupported geometry encoding for feature '{feature_name}'")
        return gdf

    def sims_with_tag(self, tag: str) -> set[str]:
        """Return the sim_ids carrying ``tag`` as a set of strings."""
        rows = self._backend.fetch_all(
            "SELECT CAST(sim_id AS VARCHAR) FROM tags WHERE tag = ?", [str(tag)]
        )
        return {str(r[0]) for r in rows}

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        rows = self._backend.fetch_all(
            "SELECT feature_name FROM geographic_features WHERE sim_id = ? ORDER BY feature_name",
            [str(sim_id)],
        )
        return [r[0] for r in rows]

    def read_geographic_metadata(self, sim_id: str | UUID) -> dict[str, str]:
        rows = self._backend.fetch_all(
            "SELECT key, value FROM geographic_metadata WHERE sim_id = ?",
            [str(sim_id)],
        )
        return {r[0]: r[1] for r in rows}

    @property
    def simulations(self) -> pd.DataFrame:
        return self._backend.query(f"{_SIMULATIONS_VIEW_SELECT} ORDER BY s.created_at DESC")

    @property
    def calibration_sessions(self) -> pd.DataFrame:
        """Return every calibration session row as a DataFrame."""
        return self._backend.query("SELECT * FROM calibration_sessions ORDER BY started_at DESC")

    def calibration_iterations(self, session_id: str | UUID) -> pd.DataFrame:
        """Return the iteration history for one session as a DataFrame."""
        sid = UUID(str(session_id)) if len(str(session_id).replace("-", "")) == 32 else session_id
        return self._backend.query(
            """
            SELECT iteration, sim_id, params_hash, parameters,
                   objective_value, metrics, status, from_cache, duration_s
              FROM calibration_iterations
             WHERE session_id = ?
             ORDER BY iteration
            """,
            [sid],
        )

    def sql(self, query: str, params: list | None = None) -> pd.DataFrame:
        """Run an arbitrary SQL query against the catalog DuckDB store.

        Documented escape hatch for callers that need ad-hoc analytical
        queries beyond the typed catalog API. Returns the result as a
        :class:`pandas.DataFrame`.
        """
        if params:
            return self._backend.query(query, params)
        return self._backend.query(query)

    def export(self, ref: str | UUID, spec: ExportSpec) -> Path:
        """Export one artifact described by *spec* for simulation *ref*.

        *ref* is resolved through :meth:`resolve` (full UUID, prefix, or a
        unique name), so callers never need the raw catalog UUID. The output
        format comes from ``spec.fmt`` (or is inferred from the destination
        extension when the spec was built).
        """
        from hydromodpy.core.config_kit.export_spec import ExportFormat

        def _single_ts(t: object) -> int:
            if t is None or t == "last":
                return -1
            if t == "first":
                return 0
            return int(t)  # type: ignore[arg-type]

        def _nc_ts(t: object) -> list[int] | None:
            if t is None or t == "all":
                return None
            if t == "first":
                return [0]
            if t == "last":
                return [-1]
            if isinstance(t, list):
                return [int(x) for x in t]
            return [int(t)]  # type: ignore[arg-type]

        sid = self.resolve(ref)
        dest = Path(spec.dest)
        fmt = spec.fmt

        if fmt is ExportFormat.hmp:
            return self.export_package(sid, dest)

        if fmt is ExportFormat.csv:
            from hydromodpy.results.exporters.csv import export_csv

            var = None if (isinstance(spec.var, str) and spec.var == "*") else spec.var_list[0]
            return export_csv(self._db, sid, dest, variable=var)

        zarr_path = str(self.zarr_path_for(sid))

        if fmt is ExportFormat.netcdf:
            from hydromodpy.results.exporters.netcdf import export_netcdf

            return export_netcdf(zarr_path, sid, spec.var_list, dest, timesteps=_nc_ts(spec.time))

        # Single-timestep raster / mesh formats.
        timestep = _single_ts(spec.time)
        variable = spec.var_list[0]

        if fmt is ExportFormat.vtu:
            from hydromodpy.results.exporters.vtu import export_vtu

            return export_vtu(zarr_path, sid, variable, timestep, dest, layer=spec.layer)

        if fmt is ExportFormat.geotiff:
            from hydromodpy.results.exporters.geotiff import export_geotiff

            resolution = (
                spec.resolution if spec.resolution is not None else self._default_resolution(sid)
            )
            crs = spec.crs if spec.crs is not None else self._export_crs_for(sid)
            return export_geotiff(
                zarr_path,
                sid,
                variable,
                timestep,
                dest,
                layer=spec.layer,
                resolution=resolution,
                crs=crs,
                nodata=spec.nodata,
            )

        if fmt is ExportFormat.shapefile:
            from hydromodpy.results.exporters.shapefile import export_shapefile

            crs = spec.crs if spec.crs is not None else self._export_crs_for(sid)
            return export_shapefile(
                zarr_path, sid, variable, timestep, dest, layer=spec.layer, crs=crs
            )

        raise ValueError(f"Unsupported export format '{fmt}'")

    def list_exports(self, ref: str | UUID) -> list[dict]:
        """Return the artefacts recorded for *ref* in ``export_log``.

        Each entry has ``kind``, ``rel_path``, ``bytes``, ``sha256`` and
        ``created_at``. Lets ``show``/``gc`` see exports without globbing.
        """
        sid = self.resolve(ref)
        rows = self._backend.fetch_all(
            "SELECT kind, rel_path, bytes, sha256, created_at "
            "FROM export_log WHERE sim_id = ? ORDER BY created_at",
            [sid],
        )
        return [
            {"kind": r[0], "rel_path": r[1], "bytes": r[2], "sha256": r[3], "created_at": r[4]}
            for r in rows
        ]

    def _export_crs_for(self, sim_id: str) -> str | None:
        row = self._backend.fetch_one(
            "SELECT crs_epsg, crs_wkt FROM simulations WHERE sim_id = ?",
            [sim_id],
        )
        if row is not None:
            epsg, wkt = row
            if epsg is not None:
                return f"EPSG:{int(epsg)}"
            if wkt:
                return str(wkt)
        try:
            sz = self.open_zarr(sim_id)
            try:
                crs = sz.root.get("crs")
                if crs is None:
                    return None
                attrs = dict(crs.attrs)
            finally:
                sz.close()
        except Exception:
            return None
        epsg_attr = attrs.get("epsg_code")
        if epsg_attr is not None:
            return f"EPSG:{int(epsg_attr)}"
        wkt_attr = attrs.get("crs_wkt")
        return str(wkt_attr) if wkt_attr else None

    def _default_resolution(self, sim_id: str) -> float | None:
        """Native cell size for raster exports when the caller omits one.

        Prefers the grid's ``cell_size`` (exact for regular grids); falls back
        to ``sqrt(area / n_cells)`` from the catalog bbox. Returns ``None`` when
        neither is available, leaving the exporter to raise a clear error.
        """
        try:
            from hydromodpy.results.run import Run

            cell_size = getattr(Run(sim_id, self).grid, "cell_size", None)
            if cell_size:
                return float(cell_size)
        except Exception:
            pass
        row = self._backend.fetch_one(
            "SELECT bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, n_cells "
            "FROM simulations WHERE sim_id = ?",
            [sim_id],
        )
        if not row:
            return None
        xmin, ymin, xmax, ymax, n_cells = row
        if None in (xmin, ymin, xmax, ymax) or not n_cells:
            return None
        area = (float(xmax) - float(xmin)) * (float(ymax) - float(ymin))
        if area <= 0 or n_cells <= 0:
            return None
        return math.sqrt(area / float(n_cells))
