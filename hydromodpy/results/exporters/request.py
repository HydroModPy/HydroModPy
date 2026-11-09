"""Write one export request of a run: expand it, plan its files, write each by kind.

A request (:class:`~hydromodpy.results.exporters.export_spec.ExportRequest`)
names data, not formats. This module reads what the run holds
(:func:`~hydromodpy.results.exporters.vocabulary.list_exportable`), expands
``"all"``, plans every file with the same
:func:`~hydromodpy.results.exporters.export_spec.plan_outputs` the check of the
document ran, refuses a file an earlier request of the run already writes,
resolves the dates to stress periods, and hands each planned file to the
format the registry resolves
(:mod:`hydromodpy.results.exporters.registry`):
(:class:`~hydromodpy.results.exporters.job.ExportJob` reads the run, the
format's ``write`` names what it writes):

- a field at one date: GeoTIFF, Shapefile, GeoPackage or VTU, one file per
  date; over several dates: one NetCDF for every field of the request;
- a series: one CSV, clipped to the simulated window unless a period says
  otherwise;
- a vector layer: GeoPackage or Shapefile; a raster layer: GeoTIFF;
- the budget: CSV;
- the whole run: its RO-Crate view, or a view an installed format serves.

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

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS, mesh_quality_values
from hydromodpy.results.derive.virtual_fields import SIMULATED_ACTIVE_NETWORK
from hydromodpy.results.exporters.export_spec import (
    EXPORT_ALL,
    MESH_LAYERS,
    ExportRequest,
    plan_outputs,
)
from hydromodpy.results.exporters.job import ExportTarget
from hydromodpy.results.exporters.registry import run_formats
from hydromodpy.results.exporters.vocabulary import (
    describe_export_names,
    describe_exportable,
    export_kind,
    list_exportable,
    network_unavailable_reason,
)
from hydromodpy.results.ledger import Ledger, record_derived_file

logger = get_logger(__name__)


EXPORT_PRODUCER = "results.exporters.request"
"""The producer an export ledger entry names; its options are the request."""


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
    taken: set[Path] = set()
    target: ExportTarget | None = None
    views = run_formats()
    for index, request in enumerate(requests):
        if request.output_format in views:
            continue
        try:
            target = target or run_export_target(store, sim_id)
            written.extend(export_request(store, sim_id, request, target, taken=taken))
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
    return f"variables = {names}" + (f", format = {fmt}" if fmt is not None else "")


def _field_root_attrs(store: Any, sim_id: str) -> dict[str, Any]:
    """Return the attributes of the root of the field store."""
    sz = store.open_zarr(sim_id)
    try:
        return dict(sz.root.attrs)
    finally:
        sz.close()


def _model_crs(store: Any, sim_id: str) -> str | None:
    """Return the CRS of the run: the one its field store records, else the one its seal states.

    ``None`` when neither says one.
    """
    from hydromodpy.results.exporters.fields import native_crs
    from hydromodpy.results.run_identity import read_sealed_manifest

    sz = store.open_zarr(sim_id)
    try:
        crs = native_crs(sz.root)
    finally:
        sz.close()
    if crs is not None:
        return crs
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
    catalog: Any,
    sim_id: str,
    request: ExportRequest,
    target: ExportTarget,
    *,
    taken: set[Path] | None = None,
) -> list[Path]:
    """Write every file ``request`` asks of one run and return their paths.

    *taken* holds the files the earlier requests of the same run write. A
    request that would write one of them again is refused before it writes
    anything, and its own files join *taken* otherwise.

    Raises
    ------
    ExportError
        A name the run does not hold, a format nothing serves, or a file of
        *taken*.
    ValueError
        A date outside the record, a format a kind cannot be written in, a
        field of several layers in a one-layer format without ``layer``.
    """
    from hydromodpy.results.exporters.job import ExportJob
    from hydromodpy.results.run import Run

    fmt = request.output_format
    if fmt is not None and fmt in run_formats():
        written = [_write_run_format(request, fmt, target)]
    else:
        from hydromodpy.results.exporters.job import ExportJob
        from hydromodpy.results.run import Run

        run = Run(sim_id, catalog)
        label = target.run_dir.name
        held = list_exportable(run)
        names = _all_names(held) if request.exports_all else request.names
        _check_held(run, label, names, held)
        kinds = {name: held[name] for name in names}
        planned = plan_outputs(request, kinds, run_label=label, names=names)
        if taken is not None:
            _hold_the_files(planned, target, taken)
        job = ExportJob(catalog=catalog, run=run, request=request, kinds=kinds, target=target)
        written = []
        for item in planned:
            writer = _format_of(item.format)
            written.extend(writer.write(job, item, _destination(item.path, target)))
    for path in written:
        _stamp(path, request, target)
    return written


def export_views(run_dir: Path, requests: Sequence[ExportRequest]) -> list[Path]:
    """Write the metadata view requests among *requests* for a sealed run; return the files.

    A view renders the seal and reads nothing else, so it is written from
    the directory alone, after the seal, without a store. The data requests
    among *requests* are left out.
    """
    target = ExportTarget.for_run(
        run_dir,
        model_crs=_read_by_data_only,
        default_resolution=_read_by_data_only,
        global_attrs=_read_by_data_only,
    )
    written: list[Path] = []
    for request in requests:
        fmt = request.output_format
        if fmt is not None and fmt in run_formats():
            written.extend(export_request(None, target.identity.sim_id, request, target))
    return written


def _read_by_data_only() -> Any:
    raise ExportError("a metadata view renders the seal; it reads no data of the run.")


def _stamp(path: Path, request: ExportRequest, target: ExportTarget) -> None:
    """Pose the identity block in a file under ``exports/`` and record it in the ledger.

    A view written in the run directory itself (a run format without
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


def _hold_the_files(planned: Sequence[Any], target: ExportTarget, taken: set[Path]) -> None:
    """Refuse a planned file an earlier request of the run writes, then add these to *taken*.

    The check of a document plans the files before the run has a name, so a
    ``file`` that takes the name of the run directory is only seen here.
    """
    landing = [_destination(item.path, target) for item in planned]
    again = sorted({path.name for path in landing if path in taken})
    if again:
        raise ExportError(
            f"{', '.join(again)} is already written by an earlier [[export]] block of this "
            "run. Give this block its own file or folder."
        )
    taken.update(landing)


def _destination(path: PurePosixPath, target: ExportTarget) -> Path:
    """Return where a planned file lands: under ``runs/<run>/exports/``."""
    return target.exports_dir / Path(path.as_posix())


def _format_of(name: str) -> object:
    """The one instance of the format *name*, resolved by the registry."""
    from hydromodpy.results.exporters.registry import export_formats

    return export_formats.get(name)()


def _check_held(run: Any, label: str, names: Sequence[str], held: Mapping[str, Any]) -> None:
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
        reasons = f"\n{SIMULATED_ACTIVE_NETWORK}: {network_unavailable_reason(run) or 'unknown'}."
    mesh_missing = [name for name in missing if name in MESH_LAYERS]
    if mesh_missing:
        from hydromodpy.results.exporters.mesh_layers import mesh_layer_reasons

        why = mesh_layer_reasons(run._catalog, run.sim_id)
        reasons += "".join(f"\n{name}: {why.get(name, 'not stored')}." for name in mesh_missing)
    raise ExportError(
        f"run {label!r} holds no {', '.join(repr(name) for name in missing)}.{reasons}\n"
        f"It can export:\n{describe_exportable(dict(held))}"
    )


def _write_run_format(request: ExportRequest, fmt: str, target: ExportTarget) -> Path:
    """Write one metadata view of the run: a whole-run format of the registry.

    A view renders the seal. Without ``folder`` or ``file`` it is written
    inside the run directory, where its relative paths resolve; a named folder
    or file under ``exports/`` gets the same view, whose paths then name the
    files of the run directory.
    """
    if request.folder is None and request.file is None:
        dest = target.run_dir
        written = _format_of(fmt).write(None, None, dest)
    else:
        (item,) = plan_outputs(request, {}, run_label=target.run_dir.name)
        dest = _destination(item.path, target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = _format_of(fmt).write(None, item, dest)
    return Path(written[0])


MAX_DEFAULT_PIXELS = 100_000_000
"""The most pixels a GeoTIFF of a field gets without a ``resolution`` named."""

CELL_AREA_FIELD = "mesh_cell_area"
"""The mesh quality field the default GeoTIFF resolution is read from."""


__all__ = [
    "MAX_DEFAULT_PIXELS",
    "EXPORT_PRODUCER",
    "export_data_requests",
    "export_request",
    "export_run",
    "export_views",
    "run_export_target",
    "regen_exports",
]
