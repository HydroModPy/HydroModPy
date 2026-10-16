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
- the whole run: its STAC, RO-Crate or PROV view.

Every data file lands under ``runs/<run>/exports/``. Each one carries the
identity block of the run (:mod:`hydromodpy.results.identity`): a GeoPackage
in its ``gpkg_metadata`` table, any other file in a ``<file>.meta.json``
sidecar, and a CSV also in its ``site`` and ``case_id`` columns. Each one gets
an entry in ``exports/index.json`` (:mod:`hydromodpy.results.ledger`), which
:func:`regen_exports` replays. A metadata view without ``folder`` or ``file``
is the crate view of the seal and sits at the root of the run directory, where
its relative paths resolve (see :func:`_stamp`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.config_kit.export_spec import (
    EXPORT_ALL,
    MESH_LAYERS,
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
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS, mesh_quality_values
from hydromodpy.results.derive.virtual_fields import (
    SIMULATED_ACTIVE_NETWORK,
    field_descriptor,
    simulated_active_network_stack,
)
from hydromodpy.results.export.ledgers import record_derived_file
from hydromodpy.results.export.run_identity import identity_of_run_dir, read_sealed_manifest
from hydromodpy.results.exporters._fields import is_timed
from hydromodpy.results.exporters._tables import (
    BUDGETS_TABLE,
    TIMESERIES_TABLE,
    read_table,
    table_path,
)
from hydromodpy.results.exporters.vocabulary import (
    describe_export_names,
    describe_exportable,
    export_kind,
    list_exportable,
)
from hydromodpy.results.identity import ZARR_IDENTITY_ATTR, Identity
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.storage.contract import RUN_EXPORTS_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


EXPORT_PRODUCER = "results.exporters.request"
"""The producer an export ledger entry names; its options are the request."""


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


MAX_DEFAULT_PIXELS = 100_000_000
"""The most pixels a GeoTIFF of a field gets without a ``resolution`` named."""

CELL_AREA_FIELD = "mesh_cell_area"
"""The mesh quality field the default GeoTIFF resolution is read from."""


def export_run(store: Any, sim_id: str, request: ExportRequest) -> list[Path]:
    """Write what one export request asks of a run; return the files written.

    *store* is whatever holds the run: the store of a run being computed or
    the catalog of a project. Every file lands under ``runs/<run>/exports/``,
    carries the identity of the run and is recorded in ``exports/index.json``.
    """
    return export_request(store, sim_id, request, run_export_target(store, sim_id))


def export_data_requests(store: Any, sim_id: str, requests: Sequence[ExportRequest]) -> list[Path]:
    """Write the data requests among *requests*, in the order of the file; return the files.

    The metadata views wait for the seal (:func:`export_views`). A request
    that fails does not stop the next one; the failures are raised together
    once every request had its turn.
    """
    failures: list[str] = []
    written: list[Path] = []
    target: ExportTarget | None = None
    for index, request in enumerate(requests):
        if request.output_format in RUN_FORMATS:
            continue
        try:
            target = target or run_export_target(store, sim_id)
            written.extend(export_request(store, sim_id, request, target))
        except Exception as exc:  # noqa: BLE001 - every request has its turn, then all raise
            failures.append(f"export request {index + 1} ({_describe(request)}): {exc}")
    if failures:
        raise ExportError(f"Export failed for run {sim_id}: " + "; ".join(failures))
    return written


def run_export_target(store: Any, sim_id: str) -> ExportTarget:
    """Return the target of one run: its directory, its identity and how its fields read."""
    return ExportTarget.for_run(
        Path(store.run_dir_for(sim_id)),
        model_crs=lambda: _model_crs(store, sim_id),
        default_resolution=lambda: _default_resolution(store, sim_id),
        global_attrs=lambda: _global_attrs(store, sim_id),
    )


def _describe(request: ExportRequest) -> str:
    """Name a request in an error: its variables and its format."""
    names = request.variables if isinstance(request.variables, str) else ", ".join(request.names)
    fmt = request.output_format
    return f"variables = {names}" + (f", format = {fmt.value}" if fmt is not None else "")


def _field_root_attrs(store: Any, sim_id: str, group: str | None = None) -> dict[str, Any]:
    """Return the attributes of the root of the field store, or of one of its groups."""
    sz = store.open_zarr(sim_id)
    try:
        node = sz.root if group is None else sz.root.get(group)
        return {} if node is None else dict(node.attrs)
    finally:
        sz.close()


def _model_crs(store: Any, sim_id: str) -> str | None:
    """Return the CRS of the run: the one its field store records, else the one its seal states.

    ``None`` when neither says one.
    """
    attrs = _field_root_attrs(store, sim_id, "crs")
    epsg = attrs.get("epsg_code")
    if epsg is not None:
        return f"EPSG:{int(epsg)}"
    wkt = attrs.get("crs_wkt")
    if wkt:
        return str(wkt)
    manifest = read_sealed_manifest(Path(store.run_dir_for(sim_id)))
    if manifest is None:
        return None
    if manifest.geometry.crs_epsg is not None:
        return f"EPSG:{manifest.geometry.crs_epsg}"
    return manifest.geometry.crs_wkt


def _default_resolution(store: Any, sim_id: str) -> float:
    """Return the native pixel size of a GeoTIFF: the side of the smallest cell of the mesh.

    It reads the mesh of the field store, never the DEM: a mesh is not
    obliged to follow the DEM pixels (cells of a regular run still give the
    DEM pixel size).

    Raises
    ------
    ValueError
        If the default gives more than :data:`MAX_DEFAULT_PIXELS` pixels over
        the extent of the mesh. The caller then names a ``resolution``.
    """
    import math

    sz = store.open_zarr(sim_id)
    try:
        areas = mesh_quality_values(sz.root, CELL_AREA_FIELD)
        vertices = np.asarray(sz.root["mesh"]["vertices"][:], dtype=np.float64)
    finally:
        sz.close()
    areas = areas[np.isfinite(areas) & (areas > 0.0)]
    if areas.size == 0:
        raise ValueError(f"Run '{sim_id}' has no cell with a positive area in its mesh.")
    resolution = math.sqrt(float(areas.min()))
    width = float(np.ptp(vertices[:, 0]))
    height = float(np.ptp(vertices[:, 1]))
    n_pixels = math.ceil(width / resolution) * math.ceil(height / resolution)
    if n_pixels > MAX_DEFAULT_PIXELS:
        raise ValueError(
            f"The default GeoTIFF resolution of run '{sim_id}' is {resolution:.3g} m "
            f"(the side of its smallest cell), which gives {n_pixels:,} pixels over the "
            f"mesh extent, above the {MAX_DEFAULT_PIXELS:,} allowed. "
            "Give a coarser resolution (resolution=...)."
        )
    return resolution


def _global_attrs(store: Any, sim_id: str) -> dict[str, Any]:
    """Return the ACDD attributes a NetCDF carries: those the seal wrote on the field store.

    A run exported before its seal has none yet; its NetCDF carries the
    identity block alone.
    """
    return {
        key: value
        for key, value in _field_root_attrs(store, sim_id).items()
        if isinstance(value, str | int | float) and not isinstance(value, bool)
    }


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

    fmt = request.output_format
    if fmt in RUN_FORMATS:
        written = [_write_run_format(request, fmt, target)]
    else:
        run = Run(sim_id, catalog)
        label = target.run_dir.name
        held = list_exportable(run)
        names = _all_names(held) if request.exports_all else request.names
        _check_held(run, label, names, held)
        kinds = {name: held[name] for name in names}
        planned = plan_outputs(request, kinds, run_label=label, names=names)
        writer = _Writer(catalog=catalog, run=run, request=request, kinds=kinds, target=target)
        written = []
        for item in planned:
            written.extend(writer.write(item, _destination(item.path, target)))
    for path in written:
        _stamp(path, request, target)
    return written


def export_views(run_dir: Path, requests: Sequence[ExportRequest]) -> list[Path]:
    """Write the metadata view requests among *requests* for a sealed run; return the files.

    A view (STAC, RO-Crate, PROV) renders the seal and reads nothing else, so
    it is written from the directory alone, after the seal, without a store.
    The data requests among *requests* are left out.
    """
    target = ExportTarget.for_run(
        run_dir,
        model_crs=_read_by_data_only,
        default_resolution=_read_by_data_only,
        global_attrs=_read_by_data_only,
    )
    written: list[Path] = []
    for request in requests:
        if request.output_format in RUN_FORMATS:
            written.extend(export_request(None, target.identity.sim_id, request, target))
    return written


def _read_by_data_only() -> Any:
    raise ExportError("a metadata view renders the seal; it reads no data of the run.")


def _stamp(path: Path, request: ExportRequest, target: ExportTarget) -> None:
    """Pose the identity block in a file under ``exports/`` and record it in the ledger.

    A view written in the run directory itself (STAC, RO-Crate, PROV without
    ``folder`` or ``file``) is left as it is: it sits at the crate root, where
    its relative paths resolve, and it renders ``manifest.json``, which already
    is the identity of the run. It gets no sidecar and no ledger entry;
    ``hmp export <run> --format <view>`` renders it again from the seal.
    """
    try:
        path.resolve().relative_to(target.exports_dir.resolve())
    except ValueError:
        return
    if path.suffix.lower() == ".gpkg":
        target.identity.write_gpkg_metadata(path)
    else:
        target.identity.write_meta_json(path)
    record_derived_file(
        target.exports_dir,
        path,
        producer=EXPORT_PRODUCER,
        options=request.model_dump(mode="json", exclude_none=True),
        identity=target.identity,
    )


def regen_exports(catalog: Any, sim_id: str, target: ExportTarget) -> list[Path]:
    """Write again every request the export ledger of a run recorded; return the files.

    Each distinct request of ``exports/index.json`` is replayed once, in the
    order it was first recorded.
    """
    ledger = Ledger.read(target.exports_dir)
    requests: list[ExportRequest] = []
    seen: list[dict[str, Any]] = []
    for entry in ledger.entries:
        if entry.producer != EXPORT_PRODUCER or entry.options in seen:
            continue
        seen.append(entry.options)
        requests.append(ExportRequest.model_validate(entry.options))
    if not requests:
        raise ExportError(
            f"{target.exports_dir} records no export to write again. Write one with "
            f"'hmp export <run> {EXPORT_ALL}' or an [[export]] block."
        )
    written: list[Path] = []
    for request in requests:
        written.extend(export_request(catalog, sim_id, request, target))
    return written


def _all_names(held: Mapping[str, Any]) -> list[str]:
    """Return what ``variables = "all"`` writes: everything but the mesh quality fields.

    ``mesh_cells`` already holds them as columns; they stay requestable by name.
    """
    return [name for name in held if name not in MESH_QUALITY_DESCRIPTORS]


def _destination(path: PurePosixPath, target: ExportTarget) -> Path:
    """Return where a planned file lands: under ``runs/<run>/exports/``."""
    return target.exports_dir / Path(path.as_posix())


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
    mesh_missing = [name for name in missing if name in MESH_LAYERS]
    if mesh_missing:
        from hydromodpy.results.exporters.mesh_layers import mesh_layer_reasons

        why = mesh_layer_reasons(run._catalog, run.sim_id)
        reasons += "".join(f"\n{name}: {why.get(name, 'not stored')}." for name in mesh_missing)
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


def _write_run_format(request: ExportRequest, fmt: ExportFormat, target: ExportTarget) -> Path:
    """Write one metadata view of the run: STAC, RO-Crate or PROV.

    A view renders the seal. Without ``folder`` or ``file`` it is written
    inside the run directory, where its relative paths resolve; a named folder
    or file under ``exports/`` gets the same view, whose paths then name the
    files of the run directory.
    """
    if request.folder is None and request.file is None:
        from hydromodpy.results.export import write_views

        (path,) = write_views(target.run_dir, formats=(fmt.value,))
        return Path(path)
    (item,) = plan_outputs(request, {}, run_label=target.run_dir.name)
    dest = _destination(item.path, target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    from hydromodpy.results.export import context_from_directory, write_ro_crate, write_stac_item
    from hydromodpy.results.export.prov import write_prov

    writers = {
        ExportFormat.stac: write_stac_item,
        ExportFormat.rocrate: write_ro_crate,
        ExportFormat.prov: write_prov,
    }
    context = context_from_directory(target.run_dir)
    return Path(writers[fmt](context, dest))


def _netcdf_identity_attrs(identity: Identity) -> dict[str, str]:
    """Return the identity block as NetCDF global attributes, the block itself as JSON text."""
    attrs = identity.as_zarr_attrs()
    attrs[ZARR_IDENTITY_ATTR] = identity.as_json()
    return {key: str(value) for key, value in attrs.items()}


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
        )

    def _quality_values(self, names: Sequence[str]) -> dict[str, np.ndarray]:
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
        if fmt is ExportFormat.shapefile:
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
        if fmt is ExportFormat.vtu:
            from hydromodpy.results.exporters.vtu import export_vtu

            return export_vtu(
                self.zarr_path, self.sim_id, name, step, dest, layer=request.layer, values=values
            )
        raise ExportError(f"a field at one date is not written as {fmt.value}.")

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

    def _budget(self, dest: Path) -> Path:
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
                fmt=item.format.value,
                crs=self.request.crs,
            )
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
    "EXPORT_PRODUCER",
    "ExportTarget",
    "contiguous_windows",
    "MAX_DEFAULT_PIXELS",
    "export_data_requests",
    "export_request",
    "export_run",
    "export_views",
    "run_export_target",
    "regen_exports",
    "step_token",
]
