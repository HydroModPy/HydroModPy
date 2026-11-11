"""What an export writer reads of a run: its target and its job.

:class:`ExportTarget` says where a request writes and who the run is,
:class:`ExportJob` reads the run and writes the planned files of one request,
by kind and format. The job holds the writing methods; a format of the port
(:mod:`hydromodpy.results.exporters.port`) names them through
:mod:`hydromodpy.results.exporters.formats`, so the format decides and the
job reads. Both moved here from ``request.py`` when the format became the
declaration, bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.selection import period_label
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS, mesh_quality_values
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    field_descriptor,
    simulated_active_network_stack,
)
from hydromodpy.results.exporters._tables import (
    BUDGETS_TABLE,
    TIMESERIES_TABLE,
    read_table,
    table_path,
)
from hydromodpy.results.exporters.export_spec import (
    MESH_LAYERS,
    STEP_DATE_TOKEN,
    ExportKind,
    ExportRequest,
    PlannedFile,
)
from hydromodpy.results.exporters.fields import is_timed
from hydromodpy.results.identity import Identity
from hydromodpy.results.record.label import identity_of_run_dir
from hydromodpy.results.storage.contract import RUN_EXPORTS_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportTarget:
    """Where a request writes and who the run is.

    ``run_dir`` is the run directory; every file lands under its
    ``exports/``. ``identity`` is the block each file carries. The three
    callables are read once, on the first file that needs them.
    """

    run_dir: Path
    identity: Identity
    model_crs: Callable[[], str | None]
    default_resolution: Callable[[], float | None]
    global_attrs: Callable[[], Mapping[str, Any]]

    @classmethod
    def for_run(
        cls,
        run_dir: Path,
        *,
        model_crs: Callable[[], str | None],
        default_resolution: Callable[[], float | None],
        global_attrs: Callable[[], Mapping[str, Any]],
    ) -> ExportTarget:
        """Return the target of one run directory, its identity read from the directory.

        Raises
        ------
        ExportError
            The directory carries neither ``manifest.json`` nor an
            ``outcome.json`` naming the run: nothing says who the files are of.
        """
        identity = identity_of_run_dir(run_dir)
        if identity is None:
            raise ExportError(
                f"{run_dir} carries neither manifest.json nor an outcome.json naming its run: "
                "an export must say which run it comes from."
            )
        return cls(
            run_dir=Path(run_dir),
            identity=identity,
            model_crs=model_crs,
            default_resolution=default_resolution,
            global_attrs=global_attrs,
        )

    @property
    def exports_dir(self) -> Path:
        """``runs/<run>/exports/``: the directory every file lands under."""
        return self.run_dir / RUN_EXPORTS_DIRNAME


def _netcdf_identity_attrs(identity: Identity) -> dict[str, str]:
    """Return the identity block as NetCDF global attributes, the block itself as JSON text."""
    from hydromodpy.results.identity import ZARR_IDENTITY_ATTR

    attrs = identity.as_zarr_attrs()
    attrs[ZARR_IDENTITY_ATTR] = identity.as_json()
    return {key: str(value) for key, value in attrs.items()}


def step_token(step: int, edges: Any) -> str:
    """Return how a file name spells the period of one step: ``2002-10``, ``step3``."""
    label = period_label(step, edges) if edges is not None else ""
    if not label:
        return f"step{step}"
    return label.replace(" to ", "_").replace(" ", "T").replace(":", "")


def contiguous_windows(steps: Any, edges: Any) -> list[tuple[Any, Any]]:
    """Return the ``(start, end)`` edges of each run of consecutive steps."""
    windows: list[tuple[Any, Any]] = []
    ordered = sorted({int(step) for step in steps})
    if not ordered:
        return windows
    first = previous = ordered[0]
    for step in ordered[1:]:
        if step != previous + 1:
            windows.append((edges[first], edges[previous + 1]))
            first = step
        previous = step
    windows.append((edges[first], edges[previous + 1]))
    return windows


@dataclass
class ExportJob:
    """Writes the planned files of one request, by kind and format.

    A format of the port names the method that writes each kind; the job
    reads the run and the request, and never knows which format dispatched.
    """

    catalog: Any
    run: Run
    request: ExportRequest
    kinds: Mapping[str, ExportKind]
    target: ExportTarget
    _network: dict[int, np.ndarray] = field(default_factory=dict)
    _cache: dict[str, Any] = field(default_factory=dict)

    @property
    def sim_id(self) -> str:
        return self.run.sim_id

    @property
    def zarr_path(self) -> str:
        return str(self.catalog.fields_path_for(self.sim_id))

    def _once(self, key: str, read: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = read()
        return self._cache[key]

    @property
    def edges(self) -> Any:
        return self._once("edges", lambda: self.run.periods.edges)

    @property
    def steps(self) -> tuple[int, ...]:
        """The periods the request selects: its dates, its period, or every one."""
        return self._once("steps", self._selected_steps)

    def _selected_steps(self) -> tuple[int, ...]:
        steps = self.run.periods.steps_for(time=self.request.time, period=self.request.period)
        if not steps:
            raise ExportError(
                "the request selects no stress period. Name a date in time, a period, "
                "or leave both out to export the whole simulation."
            )
        return steps

    @property
    def crs(self) -> str | None:
        """The CRS a reprojecting format writes: the one asked for, else the model's."""
        if self.request.crs is not None:
            return self.request.crs
        return self._once("model_crs", self.target.model_crs)

    def _network_values(self, steps: Any) -> np.ndarray:
        """Return the simulated network at ``steps``, the graph built once per request."""
        missing = [int(step) for step in steps if int(step) not in self._network]
        if missing:
            stack = simulated_active_network_stack(self.run, missing)
            self._network.update(zip(missing, stack, strict=True))
        return np.stack([self._network[int(step)] for step in steps])

    def _netcdf(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.netcdf import export_netcdf

        steps = list(self.steps)
        values: dict[str, np.ndarray] = {}
        if SIMULATED_ACTIVE_NETWORK in item.variables:
            values[SIMULATED_ACTIVE_NETWORK] = self._network_values(steps)
        values.update(self._quality_values(item.variables))
        return export_netcdf(
            self.zarr_path,
            self.sim_id,
            list(item.variables),
            dest,
            timesteps=steps,
            values=values or None,
            global_attrs={
                **self._once("global_attrs", self.target.global_attrs),
                **_netcdf_identity_attrs(self.target.identity),
            },
            layer=self.request.layer,
        )

    def _quality_values(self, names: Any) -> dict[str, np.ndarray]:
        """Return the mesh quality fields among ``names``, each one value per cell.

        They are static: a NetCDF writes them once, whatever the number of dates.
        """
        wanted = [name for name in names if name in MESH_QUALITY_DESCRIPTORS]
        if not wanted:
            return {}
        sz = self.catalog.open_zarr(self.sim_id)
        try:
            return {name: mesh_quality_values(sz.root, name) for name in wanted}
        finally:
            sz.close()

    def _field_instants(self, item: PlannedFile, dest: Path) -> list[Path]:
        """Write one field in a one-instant format: one file per date."""
        name = item.variables[0]
        timed = is_timed(field_descriptor(name))
        if item.instant is not None:
            # Read the dates as one list first: two that read one period are refused.
            _ = self.steps
            pairs = [(self.run.periods.step_at(item.instant), dest)]
        elif not timed:
            pairs = [(0, dest.with_name(dest.name.replace(f"_{STEP_DATE_TOKEN}", "")))]
        else:
            steps = self.run.periods.steps_for(period=self.request.period)
            pairs = [
                (
                    step,
                    dest.with_name(
                        dest.name.replace(STEP_DATE_TOKEN, step_token(step, self.edges))
                    ),
                )
                for step in steps
            ]
        values: dict[int, np.ndarray] = {}
        if name == SIMULATED_ACTIVE_NETWORK:
            stack = self._network_values([step for step, _ in pairs])
            values = {step: stack[row] for row, (step, _) in enumerate(pairs)}
        return [
            self._one_instant(item.format, name, step, path, values.get(step), timed)
            for step, path in pairs
        ]

    def _one_instant(
        self,
        fmt: str,
        name: str,
        step: int,
        dest: Path,
        values: np.ndarray | None,
        timed: bool,
    ) -> Path:
        request = self.request
        if fmt == "geotiff":
            from hydromodpy.results.exporters.geotiff import export_geotiff

            resolution = request.resolution
            if resolution is None:
                resolution = self._once("resolution", self.target.default_resolution)
            period = period_label(step, self.edges) if timed and self.edges is not None else None
            import pandas as pd

            model_time = None
            if timed and self.edges is not None:
                model_time = pd.Timestamp(self.edges[step + 1]).isoformat()
            return export_geotiff(
                self.zarr_path,
                self.sim_id,
                name,
                step,
                dest,
                layer=request.layer,
                resolution=resolution,
                crs=self.crs,
                nodata=request.nodata,
                values=values,
                period=period or None,
                model_time=model_time,
            )
        if fmt == "geopackage":
            if name == SIMULATED_ACTIVE_NETWORK:
                return self._active_network_vector(name, step, dest, values, driver="GPKG")

            from hydromodpy.results.exporters.geopackage import export_geopackage

            return export_geopackage(
                self.zarr_path,
                self.sim_id,
                name,
                step,
                dest,
                layer=request.layer,
                crs=self.crs,
                values=values,
            )
        if fmt == "shapefile":
            if name == SIMULATED_ACTIVE_NETWORK:
                return self._active_network_vector(
                    name, step, dest, values, driver="ESRI Shapefile"
                )

            from hydromodpy.results.exporters.shapefile import export_shapefile

            return export_shapefile(
                self.zarr_path,
                self.sim_id,
                name,
                step,
                dest,
                layer=request.layer,
                crs=self.crs,
                values=values,
            )
        if fmt == "vtu":
            from hydromodpy.results.exporters.vtu import export_vtu

            return export_vtu(
                self.zarr_path,
                self.sim_id,
                name,
                step,
                dest,
                layer=request.layer,
                values=values,
                metadata={"hydromodpy_version": self.target.identity.hydromodpy_version},
            )
        raise ExportError(f"a field at one date is not written as {fmt}.")

    def _active_network_vector(
        self,
        name: str,
        step: int,
        dest: Path,
        values: np.ndarray | None,
        *,
        driver: str,
    ) -> Path:
        """Write only the active cells of the simulated network, keeping the attribute.

        The generic cell exporter writes one polygon per mesh cell, which for a
        network holding a handful of active cells out of an entire domain is a
        file of mostly zeros. A network export names features, not a raster, so
        it keeps only the cells the network flows through.
        """
        from hydromodpy.results.exporters.shapefile import build_cell_geodataframe

        gdf = build_cell_geodataframe(
            self.zarr_path,
            self.sim_id,
            name,
            step,
            layer=self.request.layer,
            crs=self.crs,
            values=values,
            fmt=driver,
        )
        active = gdf.loc[gdf[name] != 0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if driver == "GPKG":
            active.to_file(str(dest), driver=driver, layer=name)
        else:
            active.to_file(str(dest))
        logger.info("Exported %s: %s (%d active cell(s))", driver, dest, len(active))
        return dest

    def _series(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.csv import export_csv

        edges = self.edges
        windows = None if edges is None else contiguous_windows(self.steps, edges)
        return export_csv(
            table_path(self.catalog, self.sim_id, TIMESERIES_TABLE),
            self.sim_id,
            dest,
            identity=self.target.identity,
            variables=list(item.variables),
            windows=windows,
        )

    def _budget(self, item: PlannedFile | None, dest: Path) -> Path:
        """Write the budget table, the one file a request that asks for it plans."""
        del item  # the budget holds the request's instants, not one planned name.
        from hydromodpy.results.exporters.csv import export_budget_csv

        edges = self.edges
        return export_budget_csv(
            read_table(self.catalog, self.sim_id, BUDGETS_TABLE),
            dest,
            identity=self.target.identity,
            timesteps=self.steps,
            edges=None if edges is None else list(edges),
        )

    def _vector(self, item: PlannedFile, dest: Path) -> Path:
        if item.variables[0] in MESH_LAYERS:
            from hydromodpy.results.exporters.mesh_layers import export_mesh_layers

            return export_mesh_layers(
                self.catalog,
                self.sim_id,
                list(item.variables),
                dest,
                fmt=item.format,
                crs=self.request.crs,
            )
        from hydromodpy.results.exporters.vector_layer import export_geographic_feature

        return export_geographic_feature(
            self.catalog,
            self.sim_id,
            item.variables[0],
            dest,
            fmt=item.format,
            crs=self.request.crs,
            model_crs=self._once("model_crs", self.target.model_crs),
        )

    def _raster(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.geotiff import export_geographic_raster

        return export_geographic_raster(
            self.zarr_path,
            self.sim_id,
            item.variables[0],
            dest,
            crs=self.request.crs,
            resolution=self.request.resolution,
        )


__all__ = [
    "ExportJob",
    "ExportTarget",
    "contiguous_windows",
    "step_token",
]
