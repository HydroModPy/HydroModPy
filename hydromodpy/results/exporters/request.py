"""Write one export request of a run: expand it, plan its files, write each by kind.

A request (:class:`~hydromodpy.core.config_kit.export_spec.ExportRequest`)
names data, not formats. This module reads what the run holds
(:func:`~hydromodpy.results.exporters.vocabulary.list_exportable`), expands
``"all"``, plans every file with the same
:func:`~hydromodpy.core.config_kit.export_spec.plan_outputs` the step 0 check
ran, resolves the dates to stress periods, and hands each file to the
exporter of its kind:

- a field at one date: GeoTIFF, Shapefile, GeoPackage or VTU, one file per
  date; over several dates: one NetCDF for every field of the request;
- a series: one CSV, clipped to the simulated window unless a period says
  otherwise;
- a vector layer: GeoPackage or Shapefile; a raster layer: GeoTIFF;
- the budget: CSV;
- the whole run: the ``.hmp`` package, or its STAC, RO-Crate or PROV view.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.config_kit.export_spec import (
    RUN_FORMATS,
    STEP_DATE_TOKEN,
    ExportFormat,
    ExportKind,
    ExportRequest,
    PlannedFile,
    plan_outputs,
)
from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.selection import period_label
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    field_descriptor,
    simulated_active_network_stack,
)
from hydromodpy.results.exporters._fields import is_timed
from hydromodpy.results.exporters.vocabulary import (
    describe_export_names,
    describe_exportable,
    export_kind,
    list_exportable,
)

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportTarget:
    """Where a request writes and what the catalog knows of the run.

    ``default_folder`` takes the files of a request that names no folder,
    ``share_folder`` resolves a relative ``folder``. The three callables are
    read once, on the first file that needs them.
    """

    default_folder: Path
    share_folder: Path
    model_crs: Callable[[], str | None]
    default_resolution: Callable[[], float | None]
    global_attrs: Callable[[], Mapping[str, Any]]


def export_request(
    catalog: Any, sim_id: str, request: ExportRequest, target: ExportTarget
) -> list[Path]:
    """Write every file ``request`` asks of one run and return their paths.

    Raises
    ------
    ExportError
        A name the run does not hold.
    ValueError
        A date outside the record, a format a kind cannot be written in, a
        field of several layers in a one-layer format without ``layer``.
    """
    from hydromodpy.results.run import Run

    run = Run(sim_id, catalog)
    label = run.name or sim_id[:8]
    fmt = request.output_format
    if fmt in RUN_FORMATS:
        return [_write_run_format(catalog, sim_id, request, fmt, label, target)]

    held = list_exportable(run)
    names = list(held) if request.exports_all else request.names
    _check_held(run, label, names, held)
    kinds = {name: held[name] for name in names}
    planned = plan_outputs(request, kinds, run_label=label, names=names)
    writer = _Writer(catalog=catalog, run=run, request=request, kinds=kinds, target=target)
    written: list[Path] = []
    for item in planned:
        dest = _destination(item.path, request, label, target)
        written.extend(writer.write(item, dest))
    return written


def _destination(path: PurePath, request: ExportRequest, label: str, target: ExportTarget) -> Path:
    """Return where a planned file lands on disk."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if request.folder is None:
        return target.default_folder / candidate.relative_to(label)
    return target.share_folder / candidate


def _check_held(run: Run, label: str, names: Sequence[str], held: Mapping[str, Any]) -> None:
    """Refuse a name the run does not hold, and say what it holds."""
    missing = [name for name in names if name not in held]
    if not missing:
        return
    unknown = [name for name in missing if export_kind(name) is None]
    if unknown:
        raise ExportError(
            f"no run can export {', '.join(repr(name) for name in unknown)}. "
            f"The names a run can export:\n{describe_export_names()}"
        )
    reasons = ""
    if SIMULATED_ACTIVE_NETWORK in missing:
        reasons = f"\n{SIMULATED_ACTIVE_NETWORK}: {_network_reason(run)}."
    raise ExportError(
        f"run {label!r} holds no {', '.join(repr(name) for name in missing)}.{reasons}\n"
        f"It can export:\n{describe_exportable(dict(held))}"
    )


def _network_reason(run: Run) -> str:
    """Say why a run holds no simulated stream network."""
    from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
    from hydromodpy.results.derive.stream_extent import unavailable_reason_for_flow

    try:
        settings = network_criterion_settings(run)
        reason = unavailable_reason_for_flow(run, tau_specific_ratio=settings.tau_specific_ratio)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        return str(exc)
    return reason or "unknown"


def _write_run_format(
    catalog: Any,
    sim_id: str,
    request: ExportRequest,
    fmt: ExportFormat,
    label: str,
    target: ExportTarget,
) -> Path:
    """Write the package of the run, or one of its metadata views.

    A view (STAC, RO-Crate, PROV) renders the seal. Without ``folder`` or
    ``file`` it is written inside the run directory, where its relative paths
    resolve; a named folder or file gets the same view, whose paths then name
    the files of the run directory.
    """
    if fmt is not ExportFormat.package and request.folder is None and request.file is None:
        from hydromodpy.results.export import write_views

        (path,) = write_views(catalog.run_dir_for(sim_id), formats=(fmt.value,))
        return Path(path)
    (item,) = plan_outputs(request, {}, run_label=label)
    dest = _destination(item.path, request, label, target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt is ExportFormat.package:
        return Path(catalog.export_package(sim_id, dest))
    from hydromodpy.results.export import context_from_directory, write_ro_crate, write_stac_item
    from hydromodpy.results.export.prov import write_prov

    writers = {
        ExportFormat.stac: write_stac_item,
        ExportFormat.rocrate: write_ro_crate,
        ExportFormat.prov: write_prov,
    }
    context = context_from_directory(catalog.run_dir_for(sim_id))
    return Path(writers[fmt](catalog, sim_id, dest, context=context))


def step_token(step: int, edges: Any) -> str:
    """Return how a file name spells the period of one step: ``2002-10``, ``step3``."""
    label = period_label(step, edges) if edges is not None else ""
    if not label:
        return f"step{step}"
    return label.replace(" to ", "_").replace(" ", "T").replace(":", "")


def contiguous_windows(steps: Sequence[int], edges: Any) -> list[tuple[Any, Any]]:
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
class _Writer:
    """Writes the planned files of one request, by kind and format."""

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

    def write(self, item: PlannedFile, dest: Path) -> list[Path]:
        kind = self.kinds[item.variables[0]] if item.variables else None
        if kind is ExportKind.field:
            if item.format is ExportFormat.netcdf:
                return [self._netcdf(item, dest)]
            return self._field_instants(item, dest)
        if kind is ExportKind.series:
            return [self._series(item, dest)]
        if kind is ExportKind.table:
            return [self._budget(dest)]
        if kind is ExportKind.vector:
            return [self._vector(item, dest)]
        if kind is ExportKind.raster:
            return [self._raster(item, dest)]
        raise ExportError(f"nothing writes {item.path} ({item.format.value}).")

    def _network_values(self, steps: Sequence[int]) -> np.ndarray:
        """Return the simulated network at ``steps``, the graph built once per request."""
        missing = [int(step) for step in steps if int(step) not in self._network]
        if missing:
            stack = simulated_active_network_stack(self.run, missing)
            self._network.update(zip(missing, stack, strict=True))
        return np.stack([self._network[int(step)] for step in steps])

    def _netcdf(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.netcdf import export_netcdf

        steps = list(self.steps)
        values = None
        if SIMULATED_ACTIVE_NETWORK in item.variables:
            values = {SIMULATED_ACTIVE_NETWORK: self._network_values(steps)}
        return export_netcdf(
            self.zarr_path,
            self.sim_id,
            list(item.variables),
            dest,
            timesteps=steps,
            values=values,
            global_attrs=self._once("global_attrs", self.target.global_attrs),
        )

    def _field_instants(self, item: PlannedFile, dest: Path) -> list[Path]:
        """Write one field in a one-instant format: one file per date."""
        name = item.variables[0]
        timed = is_timed(field_descriptor(name))
        if item.instant is not None:
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
        fmt: ExportFormat,
        name: str,
        step: int,
        dest: Path,
        values: np.ndarray | None,
        timed: bool,
    ) -> Path:
        request = self.request
        if fmt is ExportFormat.geotiff:
            from hydromodpy.results.exporters.geotiff import export_geotiff

            resolution = request.resolution
            if resolution is None:
                resolution = self._once("resolution", self.target.default_resolution)
            period = period_label(step, self.edges) if timed and self.edges is not None else None
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
            )
        if fmt is ExportFormat.geopackage:
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
        if fmt is ExportFormat.shapefile:
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
        if fmt is ExportFormat.vtu:
            from hydromodpy.results.exporters.vtu import export_vtu

            return export_vtu(
                self.zarr_path, self.sim_id, name, step, dest, layer=request.layer, values=values
            )
        raise ExportError(f"a field at one date is not written as {fmt.value}.")

    def _series(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.csv import export_csv

        edges = self.edges
        windows = None if edges is None else contiguous_windows(self.steps, edges)
        return export_csv(
            self.catalog.connection,
            self.sim_id,
            dest,
            variables=list(item.variables),
            windows=windows,
        )

    def _budget(self, dest: Path) -> Path:
        from hydromodpy.results.exporters.csv import export_budget_csv

        edges = self.edges
        return export_budget_csv(
            self.run.budget(),
            dest,
            timesteps=self.steps,
            edges=None if edges is None else list(edges),
        )

    def _vector(self, item: PlannedFile, dest: Path) -> Path:
        from hydromodpy.results.exporters.vector_layer import export_geographic_feature

        return export_geographic_feature(
            self.catalog,
            self.sim_id,
            item.variables[0],
            dest,
            fmt=item.format.value,
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
    "ExportTarget",
    "contiguous_windows",
    "export_request",
    "step_token",
]
