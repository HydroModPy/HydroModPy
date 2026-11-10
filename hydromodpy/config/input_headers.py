"""Read the header of each input file a configuration names, and nothing else.

``check(document, inputs=True)`` calls :func:`read_input_headers`. A local file
is opened by ``rasterio`` and only its header is read. A file given by URL goes
first through the head-only resolution of ``core/io/fetch.py``, which follows the
redirects by hand with the host and address guard at every hop and the bounds of
the call, and only then is opened as ``/vsicurl/<final URL>``, so GDAL never
sees the first URL. Nothing is downloaded and nothing is written to the cache.

Every call opens its own ``rasterio.Env``, with the few GDAL options a remote
header needs passed to it and no option set outside it. Importing this module
costs ``rasterio``, which is why ``check`` imports it only when ``inputs`` is
true.

The DEM is held to the header contract of
``catchment/terrain/dem_contract.py``: a projected CRS in metres, a grid that
is not rotated with a square pixel, a routed resolution in bounds, and an
outlet that falls on a valid cell. Any other raster has to open and to declare
a CRS, unless its table gives a ``default_crs``. A file that is not a raster
has to exist, and a URL has to answer.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import rasterio
import rasterio.crs
import rasterio.errors
import rasterio.warp
from pydantic import BaseModel
from rasterio.io import DatasetReader

from hydromodpy.catchment.terrain.dem_contract import (
    DemHeader,
    check_dem_header,
    check_dem_outlet,
    read_dem_header,
)
from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import DataContractViolation, HydroModPyError
from hydromodpy.core.io import fetch
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.tracking.input_file import InputFile

DEM_ROLE = "dem"
"""The ``InputFile`` role, and the section of ``[data]``, of a digital elevation model."""

UNREACHABLE = "input_unreachable"
"""The code of an input that is absent, refused by the bounds, or does not answer."""

BAD_HEADER = "input_header"
"""The code of an input whose header breaks the contract."""

INPUT_CODES = frozenset({UNREACHABLE, BAD_HEADER})
"""Every code this module gives."""

RASTER_SUFFIXES = frozenset({".tif", ".tiff", ".asc", ".vrt"})
"""The suffixes read as a raster by their header."""


@dataclass(frozen=True, slots=True)
class _Input:
    """One input the document names: where it is written, what it is for, and its value."""

    path: str
    role: str
    value: str
    remote: bool
    crs_fallback: str | None = None
    """The ``default_crs`` the owning table gives a raster that declares none."""


def read_input_headers(
    sections: Any, *, base: Path, bounds: Bounds | None = None
) -> list[Diagnostic]:
    """Return one diagnostic per input file whose header does not hold the contract.

    Parameters
    ----------
    sections
        The validated configuration, or a namespace of the validated sections of a
        document that is not complete. A section that is absent is skipped.
    base
        The folder a relative path is read from, the project root.
    bounds
        The hosts and the roots the call may reach. Without it, an input given by
        URL is ``input_unreachable``, never read under implicit bounds.

    Returns
    -------
    list of Diagnostic
        ``input_unreachable`` for a file that is absent, a path or a host the bounds
        refuse, or a URL that does not answer. ``input_header`` for a header that
        breaks the contract. Empty when every input holds.
    """
    inputs = list(_inputs_of(sections, ()))
    # The outlet has to fall inside the DEM only when one file is the DEM.
    alone = sum(item.role == DEM_ROLE for item in inputs) == 1
    outlet = _outlet_of(sections) if alone else None
    dem_resolution = _declared_dem_resolution(sections)
    found: list[Diagnostic] = []
    with rasterio.Env(**_gdal_options(bounds)):
        for item in inputs:
            found.extend(_read(item, base, bounds, outlet, dem_resolution))
    return found


def _declared_dem_resolution(sections: Any) -> float | None:
    """Return ``[geographic.catchment] dem_resolution`` when the document writes one."""
    geographic = getattr(sections, "geographic", None)
    value = getattr(geographic, "dem_resolution", None)
    return None if value is None else float(value)


# -- What the document names ------------------------------------------------ #


def _inputs_of(node: Any, trail: tuple[str | int, ...]) -> Iterator[_Input]:
    """Yield each input file and each URL under *node*, in the order the document holds them."""
    if isinstance(node, BaseModel):
        yield from _inputs_of_a_model(node, trail)
    elif isinstance(node, SimpleNamespace):
        for name, value in vars(node).items():
            yield from _inputs_of(value, (*trail, name))
    elif isinstance(node, Mapping):
        for name, value in node.items():
            yield from _inputs_of(value, (*trail, str(name)))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _inputs_of(value, (*trail, index))


def _inputs_of_a_model(model: BaseModel, trail: tuple[str | int, ...]) -> Iterator[_Input]:
    for name, field in type(model).model_fields.items():
        value = getattr(model, name, None)
        marker = next((meta for meta in field.metadata if isinstance(meta, InputFile)), None)
        if marker is not None and isinstance(value, (str, Path)) and str(value).strip():
            yield _Input(
                _dotted((*trail, name)),
                marker.role,
                str(value).strip(),
                remote=False,
                crs_fallback=getattr(model, "default_crs", None) or None,
            )
        elif name == "url" and getattr(model, "source", None) == "url" and isinstance(value, str):
            role = trail[1] if len(trail) > 1 and trail[0] == "data" else str(trail[-1])
            yield _Input(
                _dotted((*trail, name)),
                str(role),
                value.strip(),
                remote=True,
                crs_fallback=getattr(model, "default_crs", None) or None,
            )
        else:
            yield from _inputs_of(value, (*trail, name))
    for name, table in held_tables_of(model).items():
        yield from _inputs_of(table, (*trail, name))


def _dotted(trail: tuple[str | int, ...]) -> str:
    """Return the key of *trail* as the document spells it, ``data.dem.sources[0].path``."""
    text = ""
    for part in trail:
        text += f"[{part}]" if isinstance(part, int) else f"{'.' if text else ''}{part}"
    return text


# -- The header of one input ------------------------------------------------ #


@dataclass(frozen=True, slots=True)
class _Outlet:
    """The outlet of the catchment, as the document writes it."""

    x: float
    y: float
    crs: str | None
    """The CRS the coordinates are written in, ``None`` for the CRS of the DEM."""


def _gdal_options(bounds: Bounds | None) -> dict[str, str]:
    """Return the GDAL options a remote header read needs, held by the ``Env`` of the call."""
    timeout = bounds.timeout_s if bounds is not None else 30.0
    return {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_TIMEOUT": str(math.ceil(timeout)),
        "GDAL_HTTP_MAX_RETRY": "0",
    }


def _is_raster(item: _Input) -> bool:
    name = urlsplit(item.value).path if item.remote else item.value
    return Path(name).suffix.lower() in RASTER_SUFFIXES


def _unreachable(item: _Input, detail: str) -> Diagnostic:
    return Diagnostic(path=item.path, code=UNREACHABLE, severity="error", detail=detail)


def _read(
    item: _Input,
    base: Path,
    bounds: Bounds | None,
    outlet: _Outlet | None,
    dem_resolution: float | None,
) -> list[Diagnostic]:
    """Return the faults of *item*, opening it once when it is a raster."""
    if item.remote:
        return _read_remote(item, bounds, outlet, dem_resolution)
    candidate = Path(item.value).expanduser()
    where = candidate if candidate.is_absolute() else base / candidate
    if bounds is not None and not bounds.permits_path(where):
        roots = ", ".join(str(root) for root in bounds.allowed_roots or ())
        return [
            _unreachable(
                item, f"{where} is outside the roots this call allows ({roots or 'none'})."
            )
        ]
    if not where.exists():
        return [_unreachable(item, f"{where} does not exist.")]
    if where.is_dir() or not _is_raster(item):
        return []
    return _open(item, str(where), outlet, dem_resolution)


def _read_remote(
    item: _Input, bounds: Bounds | None, outlet: _Outlet | None, dem_resolution: float | None
) -> list[Diagnostic]:
    if bounds is None:
        return [
            _unreachable(
                item,
                f"{item.value} is read only under bounds, and this call gives none. "
                "Give the hosts the call may reach.",
            )
        ]
    try:
        location = fetch.vsicurl_path(item.value, bounds=bounds)
    except HydroModPyError as exc:
        return [_unreachable(item, getattr(exc, "message", "") or str(exc))]
    if not _is_raster(item):
        return []
    return _open(item, location, outlet, dem_resolution)


def _open(
    item: _Input, location: str, outlet: _Outlet | None, dem_resolution: float | None
) -> list[Diagnostic]:
    """Open *location* once and return the faults of its header."""
    try:
        with rasterio.open(location) as source:
            if item.role == DEM_ROLE:
                return _dem_faults(item, source, outlet, dem_resolution)
            crs = source.crs
    except (OSError, rasterio.errors.RasterioError) as exc:
        return [_unreachable(item, f"{item.value} does not open as a raster: {exc}")]
    return _crs_fault(item, crs)


def _crs_fault(item: _Input, crs: Any) -> list[Diagnostic]:
    if crs is not None or item.crs_fallback:
        return []
    return [
        Diagnostic(
            path=item.path,
            code=BAD_HEADER,
            severity="error",
            detail=f"{item.value} declares no CRS in its header.",
        )
    ]


# -- The contract of a DEM header ------------------------------------------- #


def _dem_faults(
    item: _Input,
    source: DatasetReader,
    outlet: _Outlet | None,
    dem_resolution: float | None,
) -> list[Diagnostic]:
    """Return the diagnostics of a DEM header that breaks the header contract.

    Only the header is read, never the values: the contract holds the routed
    resolution (the aggregation of ``dem_resolution`` applied), the square
    pixel, the projected CRS in metres and the cell under the outlet.
    """
    header = read_dem_header(source)
    faults: list[str] = []
    routing_res_m = dem_resolution if dem_resolution is not None else header.dx_m
    try:
        check_dem_header(header, routing_res_m=routing_res_m)
    except DataContractViolation as exc:
        faults.extend(str(failure) for failure in exc.context.get("failures", ()))
    if outlet is not None:
        cell = _outlet_in_dem_crs(header, outlet)
        if cell is not None:
            x, y = cell
            try:
                check_dem_outlet(source, header, x, y)
            except DataContractViolation as exc:
                faults.extend(str(failure) for failure in exc.context.get("failures", ()))
    diagnostics = [
        Diagnostic(
            path=item.path,
            code=BAD_HEADER,
            severity="error",
            detail=f"{item.value}: {fault}",
        )
        for fault in faults
    ]
    if header.nodata is None:
        diagnostics.append(
            Diagnostic(
                path=item.path,
                code=BAD_HEADER,
                severity="warning",
                detail=f"{item.value} declares no nodata value, so each cell is read as an elevation.",
            )
        )
    return diagnostics


def _outlet_of(sections: Any) -> _Outlet | None:
    """Return the outlet the catchment is written with, or ``None`` when it has none."""
    geographic = getattr(sections, "geographic", None)
    catchment = getattr(geographic, "catchment", None)
    x = getattr(catchment, "x_outlet", None)
    y = getattr(catchment, "y_outlet", None)
    if x is None or y is None:
        return None
    return _Outlet(float(x), float(y), getattr(geographic, "crs_project", None) or None)


def _outlet_in_dem_crs(header: DemHeader, outlet: _Outlet) -> tuple[float, float] | None:
    """Return the outlet in the CRS of the DEM, or ``None`` when it cannot be transformed.

    The outlet is written in ``[geographic] crs_project`` when that is set, else
    in the CRS of the DEM. A DEM without a CRS skips the check, refused elsewhere.
    """
    x, y = outlet.x, outlet.y
    if outlet.crs is None:
        return x, y
    if header.crs is None:
        return None
    try:
        xs, ys = rasterio.warp.transform(
            rasterio.crs.CRS.from_user_input(outlet.crs),
            rasterio.crs.CRS.from_user_input(header.crs),
            [x],
            [y],
        )
    except (rasterio.errors.CRSError, ValueError):
        # The loader refuses a CRS it cannot read, with its own diagnostic.
        return None
    return xs[0], ys[0]
