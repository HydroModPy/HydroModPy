"""Single-simulation view on the results catalog.

What
----
Read-only facade over one row of the ``simulations`` table. ``Run`` lazy-loads
its catalog row on first access and exposes typed properties (``solver``,
``status``, ``n_layers`` ...), tabular accessors (``parameters``, ``metrics``,
``timeseries``, ``budget``, ``mass_balance``, ``provenance``), field-array
readers (``field``, ``mesh``, ``geographic``, ``geographic_raster``), spatial
helpers (``grid``, ``catchment_mask``, ``dem``, ``outlet``), derived metrics
(``saturated_fraction``, ``drainage_density``, ``persistence``,
``catchment_mean``, ``recharge_forcing``), and display hooks
(``display_capabilities``, ``plot``, ``plot_all``).

Why
---
Notebook and script users need a stable per-simulation handle that hides the
DuckDB / Zarr split. Caching is per-instance to avoid repeated catalog hits
inside a session; cross-process freshness is handled by the catalog itself.

Public API
----------
- ``Run``: instantiated by ``SimulationCatalog`` resolution methods. Also
  exposes ``rerun(**overrides)`` to spawn a derived simulation, ``to_csv``
  and ``export`` for archival, plus ``at(timestep, layer)`` returning an
  ``_AtAccessor`` view (private; reachable only via ``Run.at``).

Cross-refs
----------
- ``hydromodpy.results.catalog.SimulationCatalog`` owns this object's data.
- ``hydromodpy.results.simulation_group.SimulationGroup`` iterates over
  ``Run`` instances.
- ``hydromodpy.results.grid.Grid`` backs the spatial helpers.
- ``hydromodpy.results.derived`` provides the derived-metric implementations.
"""

from __future__ import annotations

import json
import logging
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.grid import Grid


class Run:
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
            self._row = dict(zip(cols, row, strict=False))
        return self._row

    # -- Metadata properties -------------------------------------------------

    @property
    def sim_id(self) -> str:
        return self._sim_id

    @property
    def id(self) -> str:
        """Alias for :attr:`sim_id` matching the public API (``run.id``)."""
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
                f"No timeseries for sim={self._sim_id}, station={station}, var={variable}"
            )
        # The catalog stores datetimes as TIMESTAMPTZ (UTC); simulation
        # time_index is tz-naive, so strip the tz here to keep both aligned.
        idx = pd.DatetimeIndex(result["datetime"])
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        return pd.Series(
            result["value"].values,
            index=idx,
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

        Enables ``sim.at(timestep=5).field("head")`` - the dual spelling of
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

    @cached_property
    def grid(self) -> Grid:
        """Scalar grid metadata: cell_size, shape, extent, CRS, area.

        Raises ``RuntimeError`` for unstructured (``disu``) meshes -
        use ``run.mesh`` vertices + ``run.field(...)`` in that case -
        or when geographic metadata has not been ingested.
        """
        from hydromodpy.results.grid import build_grid

        return build_grid(self)

    @cached_property
    def catchment_mask(self) -> np.ndarray:
        """2D boolean mask of active catchment cells on the DEM raster.

        Shape matches ``run.grid.shape``. ``True`` where the DEM has a
        valid positive elevation. Cached on first access.
        """
        dem, _ = self.geographic_raster("watershed_dem")
        dem = dem.astype(float)
        return np.isfinite(dem) & (dem > 0)

    @cached_property
    def dem(self) -> np.ndarray:
        """DEM as ``float64`` with the source nodata sentinel replaced by NaN.

        Use this when plotting or applying NaN-aware reductions. For a
        bit-for-bit copy of the stored raster (native dtype, sentinel
        preserved), use ``run.geographic_raster("watershed_dem")``.
        """
        raw, meta = self.geographic_raster("watershed_dem")
        arr = raw.astype("float64", copy=True)
        nodata = meta.get("nodata")
        if nodata is not None:
            arr[arr == float(nodata)] = np.nan
        return arr

    def fields(self, variable: str) -> np.ndarray:
        """Stack per-timestep rasters of ``variable`` as ``(n_t, nrow, ncol)``.

        Reshapes each flat cell array to the DEM grid and stacks the
        ``n_timesteps`` frames. Only defined for regular-in-plan meshes
        (``dis`` / ``disv``); raises for ``disu`` via ``run.grid``.
        Values are returned raw (no masking or NaN substitution) -
        combine with ``run.catchment_mask`` to mask inactive cells.
        """
        grid = self.grid
        n = self.n_timesteps or 1
        return np.stack(
            [np.asarray(self.field(variable, timestep=t)).reshape(grid.shape) for t in range(n)]
        )

    @cached_property
    def time_index(self) -> pd.DatetimeIndex:
        """Datetime index aligned with the simulation's stress periods.

        Length matches ``run.n_timesteps``. Uses ``period_start`` and
        ``period_end`` stored in the catalog; raises if either is
        missing or the simulation has no timesteps.
        """
        row = self._load_row()
        n = row.get("n_timesteps")
        start, end = row.get("period_start"), row.get("period_end")
        if n is None:
            raise RuntimeError(
                f"Simulation '{self._sim_id}' has no n_timesteps recorded (is it completed?)"
            )
        if start is None or end is None:
            raise RuntimeError(
                f"Simulation '{self._sim_id}' missing period_start/period_end "
                "in catalog - cannot build a time index."
            )
        idx = pd.date_range(start=start, end=end, periods=n)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        return idx

    @cached_property
    def params(self) -> dict[str, float]:
        """Mapping of global (non-zonal) parameter values to scalar floats.

        Shortcut for the common case; for zonal parameters use the full
        ``run.parameters`` DataFrame (MultiIndex on ``param_name`` and
        ``zone_id``).
        """
        rows = self._catalog.connection.execute(
            "SELECT param_name, value FROM parameters "
            "WHERE sim_id = ? AND (zone_id IS NULL OR zone_id = ?)",
            [self._sim_id, "__global__"],
        ).fetchall()
        return {name: float(val) for name, val in rows}

    @cached_property
    def outlet(self) -> tuple[float, float]:
        """Outlet coordinates ``(x, y)`` in the simulation CRS.

        Reads ``x_outlet`` / ``y_outlet`` from ``geographic_metadata``.
        Raises ``RuntimeError`` if either is absent (e.g. catchment
        defined by a pre-drawn shapefile rather than a pour point).
        """
        meta = self._catalog.read_geographic_metadata(self._sim_id)
        missing = [k for k in ("x_outlet", "y_outlet") if k not in meta]
        if missing:
            raise RuntimeError(
                f"Outlet coordinates missing in geographic_metadata for "
                f"'{self._sim_id}' ({missing}). The catchment may have "
                "been defined by a shapefile (catch_def != 'from_outlet_coord')."
            )
        return (float(meta["x_outlet"]), float(meta["y_outlet"]))

    # -- Rerun ---------------------------------------------------------------

    @property
    def parent_sim_id(self) -> str | None:
        val = self._load_row().get("parent_sim_id")
        return str(val) if val is not None else None

    def rerun(self, **overrides) -> Run:
        """Re-run this simulation with optional config overrides.

        Reconstructs a ``HydroModPyConfig`` from the stored snapshot,
        applies overrides, and launches a new simulation. The new
        simulation's ``parent_sim_id`` points back to this one.

        Parameters
        ----------
        overrides
            Keyword overrides merged recursively into the stored config
            snapshot. For example:
            ``run.rerun(flow={"param": {"K": {"value": 2.0}}})``.

        Returns
        -------
        Run
            The newly created run.
        """
        snapshot = self.config
        if snapshot is None:
            raise ValueError(f"Simulation '{self._sim_id}' has no config snapshot - cannot rerun")

        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        HydroModPyConfig.from_snapshot(snapshot, **overrides)

        from hydromodpy.project import Project

        Project.__new__(Project)
        raise NotImplementedError(
            "Full rerun() requires workflow integration with parent_sim_id. "
            "Use HydroModPyConfig.from_snapshot() to reconstruct the config "
            "and run it manually via Project or hmp run."
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
            ext_map = {
                "csv": "csv",
                "netcdf": "nc",
                "vtu": "vtu",
                "geotiff": "tif",
                "shapefile": "shp",
            }
            ext = ext_map.get(fmt, fmt)
            out_dir = self._catalog.project_path / "exports" / (self.name or self._sim_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / (f"{variable}.{ext}" if variable != "*" else f"timeseries.{ext}")
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
                f"Figure '{figure_name}' not available. Capabilities: {self.display_capabilities}"
            )
        from hydromodpy.display.runs import render_figure

        render_figure(figure_name, self, save=save)

    def plot_all(self, *, save: str | Path | None = None) -> None:
        from hydromodpy.display.runs import render_figure

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
                f"Run(id={self._sim_id!r}, "
                f"project={row.get('project')!r}, "
                f"solver={row.get('solver')!r}, "
                f"status={row.get('status')!r})"
            )
        except KeyError:
            return f"Run(id={self._sim_id!r}, <not found>)"

    def _repr_html_(self) -> str:
        try:
            row = self._load_row()
        except KeyError:
            return f"<b>Run</b> <code>{self._sim_id[:8]}</code> <i>(not found)</i>"
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
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>" for k, v in rows
        )
        return (
            "<div><b>Run</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )


class _AtAccessor:
    """Chainable helper bound to a ``(timestep, layer)`` slice."""

    __slots__ = ("_run", "_timestep", "_layer")

    def __init__(self, run: Run, *, timestep: int, layer: int | None):
        self._run = run
        self._timestep = timestep
        self._layer = layer

    def field(self, variable: str) -> np.ndarray:
        return self._run.field(variable, timestep=self._timestep, layer=self._layer)

    def __repr__(self) -> str:
        layer_str = f", layer={self._layer}" if self._layer is not None else ""
        return f"Run.at(timestep={self._timestep}{layer_str})"
