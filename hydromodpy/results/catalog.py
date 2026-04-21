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
    GLOBAL_ZONE,
    PER_SIM_TABLE_NAMES,
    SOLVER_CATEGORIES,
    ensure_schema,
)
from hydromodpy.results.provenance import fingerprint
from hydromodpy.results.spatial_index import point_in_cell
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.simulation import SimulationView
    from hydromodpy.results.simulation_group import SimulationGroup

logger = logging.getLogger(__name__)


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

    @property
    def project_path(self) -> Path:
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
        snapshot_source = config_snapshot if config_snapshot is not None else config
        snapshot_json = (
            json.dumps(snapshot_source) if snapshot_source is not None else None
        )
        config_hash = None
        if config:
            config_hash = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()

        bbox_xmin = bbox_ymin = bbox_xmax = bbox_ymax = None
        if bbox is not None and len(bbox) == 4:
            bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax = (float(v) for v in bbox)

        crs_wkt = crs
        if crs_epsg is None and crs:
            crs_epsg = _epsg_from_crs(crs)

        topology = mesh_topology or mesh_type
        p_start = _coerce_timestamp(period_start)
        p_end = _coerce_timestamp(period_end)

        zarr_path = f"simulations/{sid}.zarr"
        parent_sid = str(parent_sim_id) if parent_sim_id else None

        self._db.execute(
            """INSERT INTO simulations
               (sim_id, name, project, solver, solver_category, flow_regime,
                n_cells, n_layers, n_timesteps,
                bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                crs_wkt, crs_epsg,
                period_start, period_end, time_unit,
                config_toml, config_snapshot, config_hash, zarr_path,
                parent_sim_id, mesh_hash, mesh_topology,
                geographic_fingerprint, tags, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                sid, name, project, solver, solver_category, flow_regime,
                n_cells, n_layers, n_timesteps,
                bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                crs_wkt, crs_epsg,
                p_start, p_end, time_unit,
                config_json, snapshot_json, config_hash, zarr_path,
                parent_sid, mesh_hash, topology,
                geographic_fingerprint, tags, notes,
            ],
        )

        if n_cells is not None and n_layers is not None:
            zarr_abs = self._workspace / zarr_path
            return SimulationZarr.create(
                zarr_abs, n_cells=n_cells, n_layers=n_layers,
                cell_types=cell_types,
                geographic_fingerprint=geographic_fingerprint,
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
            zone_val = GLOBAL_ZONE if zone is None else str(zone)
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
                "datetime": ts.index,
                "value": ts.values.astype("float64"),
                "unit": np.full(n, unit, dtype=object),
            }
        )
        self._db.execute(
            "INSERT OR REPLACE INTO timeseries "
            "(sim_id, station_id, variable, datetime, value, unit) "
            "SELECT sim_id, station_id, variable, datetime, value, unit "
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

    def write_budgets(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        if not records:
            return
        sid = str(sim_id)
        df = pd.DataFrame(records)
        df["sim_id"] = sid
        self._db.execute(
            "INSERT INTO budgets "
            "(sim_id, timestep, zone_id, component, flux_in, flux_out, unit) "
            "SELECT sim_id, timestep, zone_id, component, flux_in, flux_out, unit "
            "FROM df"
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

    def write_mass_balances(
        self,
        sim_id: str | UUID,
        records: list[dict],
    ) -> None:
        if not records:
            return
        sid = str(sim_id)
        df = pd.DataFrame(records)
        df["sim_id"] = sid
        self._db.execute(
            "INSERT INTO mass_balance "
            "(sim_id, timestep, total_in, total_out, "
            "storage_in, storage_out, percent_error) "
            "SELECT sim_id, timestep, total_in, total_out, "
            "storage_in, storage_out, percent_error FROM df"
        )

    # -- Metrics -------------------------------------------------------------

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
        source_type_value = source_type if source_type in (
            "http_api", "custom_file", "derived", "cache",
        ) else "derived"
        self._db.execute(
            """INSERT OR REPLACE INTO provenance
               (sim_id, variable, source_type, source_ref,
                period_start, period_end, payload_sha256, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(sim_id), variable, source_type_value, source_ref,
                _coerce_timestamp(period_start),
                _coerce_timestamp(period_end),
                fp["checksum"],
                int(np.prod(data.shape)),
                json.dumps(fp["stats"]),
            ],
        )

    record_provenance = write_provenance

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

    # -- Geographic features & metadata (sim-scoped in DuckDB) ----------------

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
        union_geom = unary_union(
            [g for g in gdf.geometry if g is not None and not g.is_empty]
        )
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
                str(sim_id), feature_name, geom_kind, crs_str,
                geoparquet_path, json.dumps(properties),
            ],
        )

    def read_geographic_feature(
        self, sim_id: str | UUID, feature_name: str,
    ) -> gpd.GeoDataFrame:
        import geopandas as gpd_mod

        row = self._db.execute(
            "SELECT properties, crs_wkt FROM geographic_features "
            "WHERE sim_id = ? AND feature_name = ?",
            [str(sim_id), feature_name],
        ).fetchone()
        if row is None:
            raise KeyError(
                f"Feature '{feature_name}' not found for sim '{sim_id}'"
            )
        properties_json, crs = row
        if not properties_json:
            raise KeyError(f"No payload for feature '{feature_name}'")
        props = json.loads(properties_json) if isinstance(
            properties_json, str
        ) else properties_json
        geojson_str = props.get("geojson") if isinstance(props, dict) else None
        if not geojson_str:
            raise KeyError(f"No GeoJSON data for feature '{feature_name}'")
        gdf = gpd_mod.read_file(geojson_str)
        if crs and gdf.crs is None:
            gdf = gdf.set_crs(crs)
        return gdf

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        rows = self._db.execute(
            "SELECT feature_name FROM geographic_features "
            "WHERE sim_id = ? ORDER BY feature_name",
            [str(sim_id)],
        ).fetchall()
        return [r[0] for r in rows]

    def write_geographic_metadata(
        self, sim_id: str | UUID, metadata: dict[str, object],
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
        sz.write_geographic_raster(name, data, transform=transform,
                                   crs=crs, nodata=nodata)

    # -- Zarr access ---------------------------------------------------------

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        zarr_dir = self._simulations_dir / f"{sim_id}.zarr"
        zarr_zip = self._simulations_dir / f"{sim_id}.zarr.zip"
        if zarr_zip.exists():
            return SimulationZarr(zarr_zip)
        return SimulationZarr(zarr_dir)

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
        sz.write_field(variable, timestep, values,
                       n_timesteps=n_timesteps, subgroup=subgroup)

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
        sz.write_mesh(vertices, face_node_connectivity, z_interfaces,
                      layer_indices=layer_indices,
                      source_cell_indices=source_cell_indices)

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
            raise KeyError(f"Variable '{variable}' not found for sim={sim_id}")

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
            query += " AND datetime >= ? AND datetime <= ?"
            params.extend([period[0], period[1]])
        query += " ORDER BY datetime"
        result = self._db.execute(query, params).fetchdf()
        if result.empty:
            raise KeyError(
                f"No timeseries for sim={sim_id}, station={station_id}, var={variable}"
            )
        return pd.Series(
            result["value"].values,
            index=pd.DatetimeIndex(result["datetime"]),
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
        query = "SELECT * FROM simulations"
        params: list = []
        if filters:
            clauses = []
            for key, val in filters.items():
                clauses.append(f"{key} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)
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
        zarr_path = str(self.open_zarr(sim_id).path)

        if fmt == "netcdf":
            from hydromodpy.results.exporters.netcdf import export_netcdf
            variables = [v.strip() for v in variable.split(",")]
            return export_netcdf(zarr_path, sid, variables, path, **kwargs)
        elif fmt == "csv":
            from hydromodpy.results.exporters.csv import export_csv
            return export_csv(
                self._db, sid, path,
                variable=variable if variable != "*" else None, **kwargs,
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
        return self._db.execute(
            "SELECT * FROM simulations ORDER BY created_at DESC"
        ).fetchdf()

    def __getitem__(self, sim_id: str | UUID) -> SimulationView:
        from hydromodpy.results.simulation import SimulationView

        sid = str(sim_id)
        row = self._db.execute(
            "SELECT sim_id FROM simulations WHERE sim_id = ?", [sid],
        ).fetchone()
        if row is None:
            raise KeyError(f"Simulation '{sid}' not found")
        return SimulationView(sid, self)

    def find(self, **filters) -> SimulationGroup:
        from hydromodpy.results.simulation_group import SimulationGroup

        query = "SELECT DISTINCT s.sim_id FROM simulations s"
        joins: list[str] = []
        clauses: list[str] = []
        params: list = []

        for key, val in filters.items():
            if key == "tags":
                clauses.append("list_contains(s.tags, ?)")
                params.append(val)
            elif key.endswith("_gt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ?"
                )
                params.append(metric)
                clauses.append(f"{alias}.value > ?")
                params.append(val)
            elif key.endswith("_lt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ?"
                )
                params.append(metric)
                clauses.append(f"{alias}.value < ?")
                params.append(val)
            elif key.endswith("_gte"):
                metric = key[:-4]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ?"
                )
                params.append(metric)
                clauses.append(f"{alias}.value >= ?")
                params.append(val)
            elif key == "crs":
                clauses.append("s.crs_wkt = ?")
                params.append(val)
            elif key in (
                "project", "solver", "solver_category", "flow_regime",
                "status", "name", "crs_wkt", "mesh_topology",
                "geographic_fingerprint",
            ):
                clauses.append(f"s.{key} = ?")
                params.append(val)
            else:
                raise ValueError(f"Unknown filter: '{key}'")

        if joins:
            query += " " + " ".join(joins)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.created_at DESC"

        rows = self._db.execute(query, params).fetchall()
        sim_ids = [str(r[0]) for r in rows]
        return SimulationGroup(sim_ids, self)

    def latest(self, project: str) -> SimulationView:
        from hydromodpy.results.simulation import SimulationView

        row = self._db.execute(
            "SELECT sim_id FROM simulations "
            "WHERE project = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1",
            [project],
        ).fetchone()
        if row is None:
            raise KeyError(f"No completed simulation for project '{project}'")
        return SimulationView(str(row[0]), self)

    def best(self, project: str, metric: str = "nse") -> SimulationView:
        from hydromodpy.results.simulation import SimulationView

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
                f"No completed simulation with metric '{metric}' "
                f"for project '{project}'"
            )
        return SimulationView(str(row[0]), self)

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
        self, sim_id: str | UUID, output_path: Path | str,
    ) -> Path:
        """Export a simulation as a portable ``.hmp`` archive (tar.zst).

        Returns the path to the produced ``.hmp`` file.
        """
        from hydromodpy.results.exporters.hmp_package import (
            export_hmp_package,
        )
        return export_hmp_package(self, sim_id, output_path)

    def import_package(
        self, package_path: Path | str, *, force: bool = False,
    ) -> str:
        """Import a ``.hmp`` archive into this workspace.

        SHA-256 checksums in the archive manifest are verified before any
        catalog mutation.
        """
        from hydromodpy.results.exporters.hmp_package import (
            import_hmp_package,
        )
        return import_hmp_package(self, package_path, force=force)

    # -- Lifecycle -----------------------------------------------------------

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
            zarr_dir = self._simulations_dir / f"{sid}.zarr"
            if zarr_dir.is_dir():
                try:
                    sz = SimulationZarr(zarr_dir)
                    sz.consolidate_metadata()
                    zip_path = sz.pack_to_zip()
                    rel = f"simulations/{zip_path.name}"
                    self._db.execute(
                        "UPDATE simulations SET zarr_path = ? WHERE sim_id = ?",
                        [rel, sid],
                    )
                except Exception:
                    logger.debug("Could not pack zarr to zip for sim %s", sid)

    def delete(self, sim_id: str | UUID) -> None:
        sid = str(sim_id)

        row = self._db.execute(
            "SELECT zarr_path FROM simulations WHERE sim_id = ?", [sid],
        ).fetchone()

        for table in PER_SIM_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._db.execute(
            "DELETE FROM calibration_iterations WHERE sim_id = ?", [sid],
        )
        self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])

        if row and row[0]:
            zarr_abs = self._workspace / row[0]
            if zarr_abs.is_file():
                zarr_abs.unlink(missing_ok=True)
            elif zarr_abs.is_dir():
                shutil.rmtree(zarr_abs, ignore_errors=True)

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        try:
            count = self._db.execute(
                "SELECT COUNT(*) FROM simulations"
            ).fetchone()[0]
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
                for r in self._db.execute(
                    "SELECT DISTINCT project FROM simulations"
                ).fetchall()
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
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>"
            for k, v in rows
        )
        return (
            "<div><b>SimulationCatalog</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
