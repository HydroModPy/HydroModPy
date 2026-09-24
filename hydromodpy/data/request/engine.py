"""``run_request``: load each asked-for section through its manager, write one file each.

One engine, three entries: ``hmp data get``, the ``data-request@1`` process and
this function called from Python. Each ``[data.<name>]`` section is loaded the
way a project run loads it, by its manager, over the extent and period of the
request; what comes back is cut to that extent and period and written to
``out_dir``, one file per variable and source, beside the report
``request.json``.

**The extent reaches the managers as a mask.** A box is written as a polygon
in its own CRS, and every source is handed it as ``mask_path``, which is the one
extent every manager already reads, reprojecting it the way its provider needs
(WGS84 for Hub'Eau, the grid's own CRS for SIM2, Lambert-93 for the DEM). A box
handed over as a bare tuple would carry no CRS to any of them.

**Hydrography and installed sources go through the source registry**, never
through the hydrography manager, whose job is to rasterise the network onto a
project grid with Whitebox.

**A variable that fails is listed with its error, never dropped.** The unit
is the source: when one source of a variable fails, the files it wrote are
removed and the other sources keep theirs. An empty answer -- a box at sea, no
piezometer -- is a success marked ``"empty": true``.

**The extent is resolved before anything is written.** A mask that is not a
file refuses the request with ``out_dir`` untouched.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hydromodpy.core.exceptions import DataContractViolation, DataRequestError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.data.common.source_extent import PROJECT_EXTENT_CRS, mask_extent
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.request.artefacts import (
    RASTER_SUFFIXES,
    VECTOR_SUFFIXES,
    Written,
    read_features,
    write_features,
    write_fields,
    write_points,
    write_raster,
    write_tables,
)
from hydromodpy.data.request.model import DataRequest
from hydromodpy.data.source.port import Extent, FetchRequest, Period

REPORT_NAME = "request.json"
REPORT_SCHEMA = "hmp-data-request-report/v1"
CUSTOM_SOURCE = "custom"


@dataclass(frozen=True, slots=True)
class RequestedFile:
    """What one variable and source answered, and where it was written."""

    variable: str
    source: str
    kind: str
    path: str | None
    sha256: str | None
    bytes: int | None
    crs: str | None
    bbox: tuple[float, float, float, float] | None
    period: tuple[str, str] | None
    unit: str | None
    stations: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return self.path is None


@dataclass(frozen=True, slots=True)
class RequestFailure:
    """A variable, or one of its sources, that could not be served."""

    variable: str
    source: str | None
    error: str
    exception: BaseException | None = field(default=None, compare=False, repr=False)
    """What was raised, kept for a caller that maps it to a typed exit code."""


@dataclass(frozen=True, slots=True)
class RequestReport:
    """What a request asked for, what it wrote, and what failed."""

    extent: dict[str, Any]
    period: dict[str, str] | None
    files: tuple[RequestedFile, ...]
    failures: tuple[RequestFailure, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA,
            "extent": self.extent,
            "period": self.period,
            "files": [
                {
                    "variable": item.variable,
                    "source": item.source,
                    "kind": item.kind,
                    "empty": item.empty,
                    "path": item.path,
                    "sha256": item.sha256,
                    "bytes": item.bytes,
                    "crs": item.crs,
                    "bbox": None if item.bbox is None else list(item.bbox),
                    "period": None if item.period is None else list(item.period),
                    "unit": item.unit,
                    "stations": list(item.stations),
                }
                for item in self.files
            ],
            "failures": [
                {"variable": item.variable, "source": item.source, "error": item.error}
                for item in self.failures
            ],
        }


@dataclass(frozen=True, slots=True)
class _Selector:
    """The request's extent, in the three forms the engine hands on."""

    extent: Extent | None
    mask_path: Path | None
    station_ids: tuple[str, ...]


def run_request(
    request: DataRequest,
    out_dir: str | Path,
    *,
    store: Any | None = None,
    refuse_custom: bool = False,
) -> RequestReport:
    """Serve *request* into *out_dir* and return the report written beside the files.

    *store* is the :class:`~hydromodpy.data.loading.store.DataStore` whose cache
    the managers read and fill; by default one in memory, which writes nothing.
    *refuse_custom* refuses a ``custom`` source, which a job has no user files
    for.
    """
    from hydromodpy.data.loading.store import DataStore

    target_dir = Path(out_dir)
    period = None if request.period is None else (request.period.start, request.period.end)
    files: list[RequestedFile] = []
    failures: list[RequestFailure] = []

    with TemporaryDirectory(prefix="hmp-data-request-") as scratch:
        selector = _selector(request, Path(scratch))
        target_dir.mkdir(parents=True, exist_ok=True)
        project_extent = (
            None if selector.extent is None else selector.extent.to_crs(PROJECT_EXTENT_CRS).bbox
        )
        store = store or DataStore()
        for variable, section in request.sections().items():
            try:
                _refuse_custom_sources(variable, section, refuse=refuse_custom)
                files.extend(
                    _serve_section(
                        variable,
                        _with_selector(section, selector),
                        store=store,
                        selector=selector,
                        project_extent=project_extent,
                        period=period,
                        target_dir=target_dir,
                        failures=failures,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a failed variable is reported, not raised
                failures.append(_failure(variable, None, exc))
        for installed in request.installed:
            try:
                files.extend(
                    _serve_installed(
                        installed.name,
                        installed.options,
                        selector=selector,
                        period=period,
                        scratch=Path(scratch),
                        target_dir=target_dir,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a failed source is reported, not raised
                failures.append(_failure("installed", installed.name, exc))

    report = RequestReport(
        extent=_extent_document(request),
        period=None
        if period is None
        else {"start": period[0].isoformat(), "end": period[1].isoformat()},
        files=tuple(files),
        failures=tuple(failures),
    )
    with staged_path(target_dir / REPORT_NAME) as staged:
        staged.write_text(
            json.dumps(report.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def _selector(request: DataRequest, scratch: Path) -> _Selector:
    """Resolve the extent: a box becomes a mask polygon, a mask is read, stations pass."""
    extent_in = request.extent
    if extent_in.bbox is not None:
        xmin, ymin, xmax, ymax = extent_in.bbox
        extent = Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=str(extent_in.crs))
        return _Selector(extent, _box_mask(extent, scratch), ())
    if extent_in.mask is not None:
        mask = Path(extent_in.mask.href)
        if not mask.is_file():
            raise FileNotFoundError(f"the request's mask {mask} is not a file")
        _refuse_a_mask_that_is_not_the_pinned_one(mask, extent_in.mask.sha256)
        try:
            extent = mask_extent(mask)
        except Exception as exc:
            raise DataRequestError(
                f"the request's mask {mask} cannot be read as a vector with a CRS: {exc}"
            ) from exc
        return _Selector(extent, mask, ())
    return _Selector(None, None, tuple(extent_in.station_ids))


def _refuse_a_mask_that_is_not_the_pinned_one(mask: Path, pinned: str | None) -> None:
    if pinned is None:
        return
    from hydromodpy.schema.job.digest import sha256_file

    digest, _ = sha256_file(mask)
    if digest != pinned.lower():
        raise DataContractViolation(
            f"the request's mask {mask} hashes to {digest} and the request pinned "
            f"{pinned.lower()}; the bytes are not the ones it asked for"
        )


def _failure(variable: str, source: str | None, exc: BaseException) -> RequestFailure:
    return RequestFailure(variable, source, f"{type(exc).__name__}: {exc}", exc)


def _box_mask(extent: Extent, scratch: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    path = scratch / "request_extent.gpkg"
    gpd.GeoDataFrame(geometry=[box(*extent.bbox)], crs=extent.crs).to_file(path, driver="GPKG")
    return path


def _extent_document(request: DataRequest) -> dict[str, Any]:
    extent = request.extent
    if extent.bbox is not None:
        return {"bbox": list(extent.bbox), "crs": extent.crs}
    if extent.mask is not None:
        return {"mask": extent.mask.model_dump(mode="json", exclude_none=True)}
    return {"station_ids": list(extent.station_ids)}


def _refuse_custom_sources(variable: str, section: Any, *, refuse: bool) -> None:
    if not refuse:
        return
    if any(src.source == CUSTOM_SOURCE for src in getattr(section, "sources", ())):
        raise DataRequestError(
            f"[data.{variable}] names a custom source; a job has no user files to read, "
            "so it serves only the sources that download"
        )


def _with_selector(section: Any, selector: _Selector) -> Any:
    """A copy of *section* whose sources carry the request's mask or stations."""
    updates: dict[str, Any] = {}
    if selector.mask_path is not None and "mask_path" in type(section).model_fields:
        updates["mask_path"] = selector.mask_path
    sources = []
    for src in getattr(section, "sources", ()):
        fields = type(src).model_fields
        change: dict[str, Any] = {}
        if selector.mask_path is not None and "mask_path" in fields:
            change["mask_path"] = selector.mask_path
        if selector.station_ids and "station_ids" in fields:
            change["station_ids"] = list(selector.station_ids)
        sources.append(src.model_copy(update=change) if change else src)
    if "sources" in type(section).model_fields:
        updates["sources"] = sources
    return section.model_copy(update=updates) if updates else section


def _serve_section(
    variable: str,
    section: Any,
    *,
    store: Any,
    selector: _Selector,
    project_extent: tuple | None,
    period: tuple[datetime, datetime] | None,
    target_dir: Path,
    failures: list[RequestFailure],
) -> list[RequestedFile]:
    if variable == "hydrography":
        return _serve_hydrography(
            section, selector=selector, target_dir=target_dir, failures=failures
        )
    if variable == "dem":
        result = store.load_dem(section, project_extent=project_extent)
    elif variable == "geology":
        result = store.load_geology(section, project_extent=project_extent)
    else:
        result = store.load_variable(
            variable, section, project_extent=project_extent, project_period=period
        )
    sources = [src.source for src in getattr(section, "sources", ())]
    return _write_result(
        variable,
        result,
        sources,
        extent=selector.extent,
        period=period,
        target_dir=target_dir,
        failures=failures,
    )


def _write_result(
    variable: str,
    result: LoadResult,
    sources: Iterable[str],
    *,
    extent: Extent | None,
    period: tuple[datetime, datetime] | None,
    target_dir: Path,
    failures: list[RequestFailure],
) -> list[RequestedFile]:
    """Write one file per source of *result*, and an empty entry for a silent one."""
    by_source: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for record in result.points:
        by_source[record.source]["points"].append(record)
    for record in result.fields:
        if not record.is_file_reference:
            by_source[record.source]["fields"].append(record)
        elif Path(record.data).suffix.lower() in RASTER_SUFFIXES:
            by_source[record.source]["raster"].append(record)
        elif Path(record.data).suffix.lower() in VECTOR_SUFFIXES:
            by_source[record.source]["vector"].append(record)
        else:
            by_source[record.source]["fields"].append(record)
    for record in result.tables:
        by_source[record.source]["table"].append(record)

    files: list[RequestedFile] = []
    for source in dict.fromkeys([*sources, *by_source]):
        kinds = by_source.get(source, {})
        if not kinds:
            files.append(_empty(variable, source, "none"))
            continue
        files.extend(
            _one_source(
                variable,
                source,
                failures,
                target_dir,
                lambda entries, source=source, kinds=kinds: _write_kinds(
                    variable, source, kinds, extent, period, target_dir, entries
                ),
            )
        )
    return files


def _one_source(
    variable: str,
    source: str,
    failures: list[RequestFailure],
    target_dir: Path,
    write: Callable[[list[RequestedFile]], object],
) -> list[RequestedFile]:
    """Run the writers of one source; on failure, remove its files and record why."""
    entries: list[RequestedFile] = []
    try:
        write(entries)
    except Exception as exc:  # noqa: BLE001 - a failed source is reported, not raised
        for entry in entries:
            if entry.path is not None:
                (target_dir / entry.path).unlink(missing_ok=True)
        failures.append(_failure(variable, source, exc))
        return []
    return entries


def _write_kinds(
    variable: str,
    source: str,
    kinds: dict[str, list],
    extent: Extent | None,
    period: tuple[datetime, datetime] | None,
    target_dir: Path,
    entries: list[RequestedFile],
) -> None:
    for kind, records in kinds.items():
        _write_kind(variable, source, kind, records, extent, period, target_dir, entries)


def _write_kind(
    variable: str,
    source: str,
    kind: str,
    records: list,
    extent: Extent | None,
    period: tuple[datetime, datetime] | None,
    target_dir: Path,
    entries: list[RequestedFile],
) -> None:
    """Write the records of one kind, appending each file to *entries* as it lands."""
    stem = f"{variable}_{source}"
    unit = next((r.unit for r in records if getattr(r, "unit", None)), None)
    if kind == "points":
        written = write_points(records, target_dir / f"{stem}.parquet", period=period)
        stations = tuple(sorted({r.station_id for r in records}))
        entries.append(_entry(variable, source, kind, written, target_dir, unit, stations))
        return
    if kind == "fields":
        written = write_fields(records, target_dir / f"{stem}.nc", extent=extent, period=period)
        entries.append(_entry(variable, source, kind, written, target_dir, unit, ()))
        return
    if kind == "table":
        written = write_tables(records, target_dir / f"{stem}.parquet")
        entries.append(_entry(variable, source, kind, written, target_dir, unit, ()))
        return
    for index, record in enumerate(records):
        name = stem if len(records) == 1 else f"{stem}_{index + 1}"
        if kind == "raster":
            written = write_raster(Path(record.data), target_dir / f"{name}.tif", extent=extent)
        else:
            frame = read_features(Path(record.data))
            written = write_features(frame, target_dir / f"{name}.gpkg", extent=extent)
        entries.append(_entry(variable, source, kind, written, target_dir, unit, ()))


def _serve_hydrography(
    section: Any,
    *,
    selector: _Selector,
    target_dir: Path,
    failures: list[RequestFailure],
) -> list[RequestedFile]:
    """Ask each source for the network over the extent, without the Whitebox manager."""
    if selector.extent is None:
        raise DataRequestError(
            "hydrography is asked over an extent; a list of stations bounds nothing"
        )
    files = []
    for src in section.sources:
        files.extend(
            _one_source(
                "hydrography",
                src.source,
                failures,
                target_dir,
                lambda entries, src=src: _write_network(src, selector, target_dir, entries),
            )
        )
    return files


def _write_network(
    src: Any, selector: _Selector, target_dir: Path, entries: list[RequestedFile]
) -> None:
    from hydromodpy.data.variables.hydrography import custom
    from hydromodpy.data.variables.hydrography.api_source import (
        fetch_network,
        source_from_section,
    )

    stem = f"hydrography_{src.source}"
    if src.source == CUSTOM_SOURCE:
        loaded = custom.load_custom(src)
        if isinstance(loaded, Path):
            written = write_raster(loaded, target_dir / f"{stem}.tif", extent=selector.extent)
            entries.append(
                _entry("hydrography", src.source, "raster", written, target_dir, None, ())
            )
            return
        frame = loaded
    else:
        frame = fetch_network(source_from_section(src), selector.extent)
    written = write_features(frame, target_dir / f"{stem}.gpkg", extent=selector.extent)
    entries.append(_entry("hydrography", src.source, "vector", written, target_dir, None, ()))


def _serve_installed(
    name: str,
    options: dict[str, Any],
    *,
    selector: _Selector,
    period: tuple[datetime, datetime] | None,
    scratch: Path,
    target_dir: Path,
) -> list[RequestedFile]:
    """Ask a plugin source through the port, and write what it answers by its kind."""
    from hydromodpy.data.source import registry

    try:
        source = registry.get(name)(**options)
    except Exception as exc:
        # An installed source is somebody else's code reading somebody else's
        # options; its refusal is a fault of the request, not of HydroModPy.
        raise DataRequestError(
            f"source {name!r} refused the options this request carries: {type(exc).__name__}: {exc}"
        ) from exc
    out = scratch / f"installed-{name}"
    out.mkdir(parents=True, exist_ok=True)
    result = source.fetch(
        FetchRequest(
            out_dir=out,
            extent=selector.extent,
            station_ids=selector.station_ids,
            period=None if period is None else Period(start=period[0], end=period[1]),
        )
    )
    variable = ",".join(result.variables)
    stem = f"installed_{name}"
    writers: dict[str, Callable[[], Written | None]] = {
        "points": lambda: write_points(
            result.points, target_dir / f"{stem}.parquet", period=period
        ),
        "fields": lambda: write_fields(
            result.fields, target_dir / f"{stem}.nc", extent=selector.extent, period=period
        ),
        "features": lambda: write_features(
            result.features, target_dir / f"{stem}.gpkg", extent=selector.extent
        ),
        "files": lambda: write_raster(
            Path(result.files[0]), target_dir / f"{stem}.tif", extent=selector.extent
        ),
    }
    written = None if result.is_empty else writers[result.kind]()
    return [_entry(variable, name, result.kind, written, target_dir, None, ())]


def _empty(variable: str, source: str, kind: str) -> RequestedFile:
    return RequestedFile(variable, source, kind, None, None, None, None, None, None, None, ())


def _entry(
    variable: str,
    source: str,
    kind: str,
    written: Written | None,
    target_dir: Path,
    unit: str | None,
    stations: tuple[str, ...],
) -> RequestedFile:
    if written is None:
        return _empty(variable, source, kind)
    from hydromodpy.schema.job.digest import sha256_file

    digest, size = sha256_file(written.path)
    return RequestedFile(
        variable=variable,
        source=source,
        kind=kind,
        path=written.path.relative_to(target_dir).as_posix(),
        sha256=digest,
        bytes=size,
        crs=written.crs,
        bbox=written.bbox,
        period=written.period,
        unit=unit,
        stations=stations,
    )


__all__ = [
    "REPORT_NAME",
    "REPORT_SCHEMA",
    "RequestFailure",
    "RequestReport",
    "RequestedFile",
    "run_request",
]
