from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.zarr_store import SimulationZarr


class Simulation:

    def __init__(self, sim_id: str, catalog: SimulationCatalog) -> None:
        self._sim_id = sim_id
        self._catalog = catalog
        self._row: dict | None = None

    def _load_row(self) -> dict:
        if self._row is None:
            row = self._catalog.connection.execute(
                "SELECT * FROM simulations WHERE sim_id = ?",
                [self._sim_id],
            ).fetchone()
            if row is None:
                raise KeyError(f"Simulation '{self._sim_id}' not found")
            cols = [d[0] for d in self._catalog.connection.description]
            self._row = dict(zip(cols, row))
        return self._row

    # -- Metadata properties -------------------------------------------------

    @property
    def id(self) -> str:
        return self._sim_id

    @property
    def name(self) -> str | None:
        return self._load_row().get("name")

    @property
    def project(self) -> str:
        return self._load_row()["project"]

    @property
    def solver(self) -> str | None:
        return self._load_row().get("solver")

    @property
    def solver_category(self) -> str | None:
        return self._load_row().get("solver_category")

    @property
    def flow_regime(self) -> str | None:
        return self._load_row().get("flow_regime")

    @property
    def status(self) -> str | None:
        return self._load_row().get("status")

    @property
    def created_at(self):
        return self._load_row().get("created_at")

    @property
    def duration_s(self) -> float | None:
        return self._load_row().get("duration_s")

    @property
    def config(self) -> dict | None:
        val = self._load_row().get("config_toml")
        if val is None:
            return None
        if isinstance(val, str):
            return json.loads(val)
        return val

    @property
    def tags(self) -> list[str] | None:
        return self._load_row().get("tags")

    @property
    def n_layers(self) -> int | None:
        return self._load_row().get("n_layers")

    @property
    def n_cells(self) -> int | None:
        return self._load_row().get("n_cells")

    @property
    def n_timesteps(self) -> int | None:
        return self._load_row().get("n_timesteps")

    # -- Tabular data properties ---------------------------------------------

    @property
    def parameters(self) -> pd.DataFrame:
        return self._catalog.connection.execute(
            "SELECT param_name, zone_id, value, unit, parameterization "
            "FROM parameters WHERE sim_id = ? ORDER BY param_name, zone_id",
            [self._sim_id],
        ).fetchdf()

    @property
    def metrics(self) -> pd.DataFrame:
        return self._catalog.connection.execute(
            "SELECT station_id, metric_name, value "
            "FROM metrics WHERE sim_id = ? ORDER BY station_id, metric_name",
            [self._sim_id],
        ).fetchdf()

    @property
    def provenance(self) -> pd.DataFrame:
        return self._catalog.connection.execute(
            "SELECT variable, source_type, source_ref, checksum, "
            "period_start, period_end, n_records "
            "FROM provenance WHERE sim_id = ?",
            [self._sim_id],
        ).fetchdf()

    # -- Data access ---------------------------------------------------------

    def timeseries(
        self,
        variable: str,
        station: str,
        period: tuple | None = None,
    ) -> pd.Series:
        query = (
            "SELECT timestamp, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [self._sim_id, station, variable]
        if period is not None:
            query += " AND timestamp >= ? AND timestamp <= ?"
            params.extend([period[0], period[1]])
        query += " ORDER BY timestamp"
        result = self._catalog.connection.execute(query, params).fetchdf()
        if result.empty:
            raise KeyError(
                f"No timeseries for sim={self._sim_id}, "
                f"station={station}, var={variable}"
            )
        return pd.Series(
            result["value"].values,
            index=pd.DatetimeIndex(result["timestamp"]),
            name=variable,
        )

    def budget(
        self,
        component: str | None = None,
        zone_id: str | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        query = "SELECT * FROM budgets WHERE sim_id = ?"
        params: list = [self._sim_id]
        if component is not None:
            query += " AND component = ?"
            params.append(component)
        if zone_id is not None:
            query += " AND zone_id = ?"
            params.append(zone_id)
        if period is not None:
            query += " AND timestep >= ? AND timestep <= ?"
            params.extend(period)
        return self._catalog.connection.execute(query, params).fetchdf()

    @property
    def mass_balance(self) -> pd.DataFrame:
        return self._catalog.connection.execute(
            "SELECT * FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [self._sim_id],
        ).fetchdf()

    def field(
        self,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        sz = self._catalog.open_zarr(self._sim_id)
        n_ts = self._load_row().get("n_timesteps")
        if n_ts is not None and timestep < 0:
            timestep = n_ts + timestep
        return sz.read_field(variable, timestep, layer=layer)

    @property
    def mesh(self) -> dict:
        sz = self._catalog.open_zarr(self._sim_id)
        mesh_grp = sz.root["mesh"]
        return {
            "vertices": mesh_grp["vertices"][:],
            "face_node_connectivity": mesh_grp["face_node_connectivity"][:],
            "z_interfaces": mesh_grp["z_interfaces"][:],
        }

    # -- Geographic ----------------------------------------------------------

    def geographic(self, feature_name: str) -> gpd.GeoDataFrame:
        import geopandas as gpd_mod

        row = self._catalog.connection.execute(
            "SELECT geojson, crs FROM geographic_features "
            "WHERE project = ? AND feature_name = ?",
            [self.project, feature_name],
        ).fetchone()
        if row is None:
            raise KeyError(
                f"Feature '{feature_name}' not found for project '{self.project}'"
            )
        geojson_str, crs = row
        if geojson_str:
            gdf = gpd_mod.read_file(geojson_str)
            if crs and gdf.crs is None:
                gdf = gdf.set_crs(crs)
            return gdf
        raise KeyError(f"No GeoJSON data for feature '{feature_name}'")

    def geographic_raster(self, name: str) -> tuple[np.ndarray, dict]:
        sz = self._catalog.open_zarr(self._sim_id)
        return sz.read_geographic_raster(name)

    # -- Export convenience --------------------------------------------------

    def to_csv(self, path: Path | str | None = None) -> pd.DataFrame:
        df = self._catalog.connection.execute(
            "SELECT station_id, variable, timestamp, value, unit "
            "FROM timeseries WHERE sim_id = ? ORDER BY station_id, variable, timestamp",
            [self._sim_id],
        ).fetchdf()
        if path is not None:
            df.to_csv(str(path), index=False)
        return df

    # -- Display capabilities ------------------------------------------------

    @property
    def display_capabilities(self) -> list[str]:
        caps = ["watertable_map", "budget_chart"]
        row = self._load_row()

        n_layers = row.get("n_layers") or 0
        if n_layers > 1:
            caps.append("cross_section")

        if row.get("flow_regime") == "transient":
            caps.extend(["streamflow", "head_timeseries", "drainage_density"])

        sz = self._catalog.open_zarr(self._sim_id)
        if "concentration" in sz.root:
            caps.append("concentration_map")
        if "pathlines" in sz.root:
            caps.append("pathlines")

        return caps

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        try:
            row = self._load_row()
            return (
                f"Simulation(id={self._sim_id!r}, "
                f"project={row.get('project')!r}, "
                f"solver={row.get('solver')!r}, "
                f"status={row.get('status')!r})"
            )
        except KeyError:
            return f"Simulation(id={self._sim_id!r}, <not found>)"
