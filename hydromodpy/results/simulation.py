from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.catalog import SimulationCatalog


class SimulationView:

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
    def sim_id(self) -> str:
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
        """Calibratable parameters persisted for this run.

        Returns a ``DataFrame`` indexed by ``param_name`` (or by the
        ``(param_name, zone_id)`` MultiIndex when a parameter is zonal)
        with columns ``value``, ``unit``, ``parameterization``. Homogeneous
        scalars are trivially looked up via
        ``sim.parameters.loc["thickness", "value"]``.
        """
        df = self._catalog.connection.execute(
            "SELECT param_name, zone_id, value, unit, parameterization "
            "FROM parameters WHERE sim_id = ? ORDER BY param_name, zone_id",
            [self._sim_id],
        ).fetchdf()
        # Homogeneous params have zone_id=NULL in the DB (stored as
        # "__global__" by the writer); hide that column from the canonical
        # view unless zonal rows are present.
        if df.empty:
            return df.set_index("param_name")
        is_zonal = df["zone_id"].fillna("__global__") != "__global__"
        if is_zonal.any():
            df["zone_id"] = df["zone_id"].fillna("__global__")
            return df.set_index(["param_name", "zone_id"])
        return df.drop(columns=["zone_id"]).set_index("param_name")

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
            "SELECT variable, source_type, source_ref, "
            "payload_sha256 AS checksum, "
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
            "SELECT datetime, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [self._sim_id, station, variable]
        if period is not None:
            query += " AND datetime >= ? AND datetime <= ?"
            params.extend([period[0], period[1]])
        query += " ORDER BY datetime"
        result = self._catalog.connection.execute(query, params).fetchdf()
        if result.empty:
            raise KeyError(
                f"No timeseries for sim={self._sim_id}, "
                f"station={station}, var={variable}"
            )
        return pd.Series(
            result["value"].values,
            index=pd.DatetimeIndex(result["datetime"]),
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
        timestep: int = -1,
        layer: int | None = None,
    ) -> np.ndarray:
        sz = self._catalog.open_zarr(self._sim_id)
        n_ts = self._load_row().get("n_timesteps")
        if n_ts is not None and timestep < 0:
            timestep = n_ts + timestep
        return sz.read_field(variable, timestep, layer=layer)

    def at(self, timestep: int = -1, layer: int | None = None) -> _AtAccessor:
        """Return a chainable accessor bound to ``(timestep, layer)``.

        Enables ``sim.at(timestep=5).field("head")`` — the dual spelling of
        ``sim.field("head", timestep=5)``. Useful in notebook sessions where
        the same slice is reused across several variables.
        """
        return _AtAccessor(self, timestep=timestep, layer=layer)

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
        return self._catalog.read_geographic_feature(self._sim_id, feature_name)

    def geographic_raster(self, name: str) -> tuple[np.ndarray, dict]:
        sz = self._catalog.open_zarr(self._sim_id)
        return sz.read_geographic_raster(name)

    # -- Rerun ---------------------------------------------------------------

    @property
    def parent_sim_id(self) -> str | None:
        val = self._load_row().get("parent_sim_id")
        return str(val) if val is not None else None

    def rerun(self, **overrides) -> SimulationView:
        """Re-run this simulation with optional config overrides.

        Reconstructs a ``HydroModPyConfig`` from the stored snapshot,
        applies overrides, and launches a new simulation. The new
        simulation's ``parent_sim_id`` points back to this one.

        Parameters
        ----------
        **overrides
            Nested config overrides merged recursively into the snapshot.
            For example: ``sim.rerun(flow={"param": {"K": {"value": 2.0}}})``.

        Returns
        -------
        SimulationView
            The newly created simulation.
        """
        snapshot = self.config
        if snapshot is None:
            raise ValueError(
                f"Simulation '{self._sim_id}' has no config snapshot — cannot rerun"
            )

        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        new_config = HydroModPyConfig.from_snapshot(snapshot, **overrides)

        from hydromodpy.project import Simulation

        # Build a minimal Simulation-like execution from the reconstructed config
        # and register with parent_sim_id linkage.
        project = Simulation.__new__(Simulation)
        # This is a stub — full rerun integration requires the workflow to
        # accept a pre-built config + parent_sim_id. For now, store the
        # config and parent reference so callers can wire them.
        raise NotImplementedError(
            "Full rerun() requires workflow integration with parent_sim_id. "
            "Use HydroModPyConfig.from_snapshot() to reconstruct the config "
            "and run it manually via Simulation or hmp run."
        )

    # -- Export convenience --------------------------------------------------

    def to_csv(self, path: Path | str | None = None) -> pd.DataFrame:
        df = self._catalog.connection.execute(
            "SELECT station_id, variable, datetime, value, unit "
            "FROM timeseries WHERE sim_id = ? "
            "ORDER BY station_id, variable, datetime",
            [self._sim_id],
        ).fetchdf()
        if path is not None:
            df.to_csv(str(path), index=False)
        return df

    # -- Export --------------------------------------------------------------

    def export(
        self,
        variable: str = "*",
        fmt: str = "csv",
        path: str | Path | None = None,
        **kwargs,
    ) -> None:
        """Export results to a file.

        Parameters
        ----------
        variable : str
            Variable name or ``"*"`` for all timeseries.
        fmt : str
            ``"csv"``, ``"netcdf"``, ``"geotiff"``, ``"vtu"``, ``"shapefile"``.
        path : Path, optional
            Output file path. Defaults to
            ``<workspace>/exports/<name>/<variable>.<ext>``.
        """
        if path is None:
            ext_map = {"csv": "csv", "netcdf": "nc", "vtu": "vtu",
                       "geotiff": "tif", "shapefile": "shp"}
            ext = ext_map.get(fmt, fmt)
            out_dir = self._catalog.project_path / "exports" / (self.name or self._sim_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / (
                f"{variable}.{ext}" if variable != "*" else f"timeseries.{ext}"
            )
        self._catalog.export(self._sim_id, variable, fmt, path, **kwargs)

    # -- Lazy catchment views (delegate to hydromodpy.results.views) ---------

    def saturated_fraction(self, **kwargs) -> pd.Series:
        """Lazy ``%`` of catchment cells where seepage > threshold per step."""
        from hydromodpy.results import views
        return views.saturated_fraction(self, **kwargs)

    def drainage_density(self, **kwargs) -> pd.Series:
        """Lazy ``%`` of catchment cells with positive routed drain flux."""
        from hydromodpy.results import views
        return views.drainage_density(self, **kwargs)

    def persistence(self, **kwargs) -> np.ndarray:
        """Lazy per-cell fraction of timesteps above a threshold."""
        from hydromodpy.results import views
        return views.persistence(self, **kwargs)

    def catchment_mean(self, variable: str, **kwargs) -> pd.Series:
        """Lazy arithmetic mean of a cell variable over active cells."""
        from hydromodpy.results import views
        return views.catchment_mean(self, variable, **kwargs)

    def recharge_forcing(self) -> pd.Series:
        """Lazy input recharge forcing per stress period."""
        from hydromodpy.results import views
        return views.recharge_forcing(self)

    # -- Display capabilities ------------------------------------------------

    @property
    def display_capabilities(self) -> list[str]:
        caps = ["piezometric_map", "water_budget"]
        row = self._load_row()

        n_layers = row.get("n_layers") or 0
        if n_layers > 1:
            caps.append("cross_section")

        if row.get("flow_regime") == "transient":
            caps.append("hydrograph")

        sz = self._catalog.open_zarr(self._sim_id)
        if "concentration" in sz.root:
            caps.append("concentration_map")
        if "pathlines" in sz.root:
            caps.append("particle_tracks")

        return caps

    def plot(self, figure_name: str, *, save: str | Path | None = None) -> None:
        if figure_name not in self.display_capabilities:
            raise ValueError(
                f"Figure '{figure_name}' not available. "
                f"Capabilities: {self.display_capabilities}"
            )
        from hydromodpy.results.display import render_figure

        render_figure(figure_name, self, save=save)

    def plot_all(self, *, save: str | Path | None = None) -> None:
        from hydromodpy.results.display import render_figure

        for name in self.display_capabilities:
            try:
                render_figure(name, self, save=save)
            except Exception:
                logger.warning("Failed to render '%s'", name)

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        try:
            row = self._load_row()
            return (
                f"SimulationView(id={self._sim_id!r}, "
                f"project={row.get('project')!r}, "
                f"solver={row.get('solver')!r}, "
                f"status={row.get('status')!r})"
            )
        except KeyError:
            return f"SimulationView(id={self._sim_id!r}, <not found>)"

    def _repr_html_(self) -> str:
        try:
            row = self._load_row()
        except KeyError:
            return f"<b>SimulationView</b> <code>{self._sim_id[:8]}</code> <i>(not found)</i>"
        dur = row.get("duration_s")
        dur_str = f"{dur:.1f} s" if isinstance(dur, (int, float)) else "&mdash;"
        rows = [
            ("sim_id", f"<code>{self._sim_id}</code>"),
            ("name", str(row.get("name") or "&mdash;")),
            ("project", str(row.get("project") or "&mdash;")),
            ("solver", str(row.get("solver") or "&mdash;")),
            ("status", str(row.get("status") or "&mdash;")),
            ("duration", dur_str),
            ("n_cells", str(row.get("n_cells") or "&mdash;")),
            ("n_timesteps", str(row.get("n_timesteps") or "&mdash;")),
        ]
        body = "".join(
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>"
            for k, v in rows
        )
        return (
            "<div><b>SimulationView</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )


class _AtAccessor:
    """Chainable helper bound to a ``(timestep, layer)`` slice."""

    __slots__ = ("_sim", "_timestep", "_layer")

    def __init__(self, sim: SimulationView, *, timestep: int, layer: int | None):
        self._sim = sim
        self._timestep = timestep
        self._layer = layer

    def field(self, variable: str) -> np.ndarray:
        return self._sim.field(variable, timestep=self._timestep, layer=self._layer)

    def __repr__(self) -> str:
        layer_str = f", layer={self._layer}" if self._layer is not None else ""
        return f"SimulationView.at(timestep={self._timestep}{layer_str})"
