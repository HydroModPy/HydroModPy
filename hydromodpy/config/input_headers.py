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

The DEM is held to the contract of ``data/schemas/dem.py`` and to three checks
that need a header: a projected CRS in metres, a grid that is not rotated with
a square pixel, and an outlet that falls on a valid cell. Any other raster has
to open and to declare a CRS, unless its table gives a ``default_crs``. A file
that is not a raster has to exist, and a URL has to answer.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import rasterio
import rasterio.crs
import rasterio.errors
import rasterio.warp
from pydantic import BaseModel
from rasterio.windows import Window

from hydromodpy.core.config_kit.introspect import held_tables_of
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import DataContractViolation, HydroModPyError
from hydromodpy.core.io import fetch
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.schemas.dem import DEMContract, validate_dem

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

SQUARE_PIXEL_TOLERANCE = 1e-6
"""The relative gap between the two pixel sizes below which the pixel is square."""


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
    found: list[Diagnostic] = []
    with rasterio.Env(**_gdal_options(bounds)):
        for item in inputs:
            is_dem = item.role == DEM_ROLE
            header, faults = _read(item, base, bounds, outlet if is_dem else None)
            found.extend(faults)
            if header is not None and is_dem:
                found.extend(_dem_faults(item, header))
    return found


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


@dataclass(frozen=True, slots=True)
class _Header:
    """What the contract reads of a raster header."""

    crs: Any
    transform: Any
    nodata: float | None
    outlet_fault: str | None = None
    """What is wrong with the cell of the outlet, read while the file was open."""


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
    item: _Input, base: Path, bounds: Bounds | None, outlet: _Outlet | None
) -> tuple[_Header | None, list[Diagnostic]]:
    """Return the header of *item* when it is a raster that opens, and the faults found on the way."""
    if item.remote:
        return _read_remote(item, bounds, outlet)
    candidate = Path(item.value).expanduser()
    where = candidate if candidate.is_absolute() else base / candidate
    if bounds is not None and not bounds.permits_path(where):
        roots = ", ".join(str(root) for root in bounds.allowed_roots or ())
        return None, [
            _unreachable(
                item, f"{where} is outside the roots this call allows ({roots or 'none'})."
            )
        ]
    if not where.exists():
        return None, [_unreachable(item, f"{where} does not exist.")]
    if where.is_dir() or not _is_raster(item):
        return None, []
    return _open(item, str(where), outlet)


def _read_remote(
    item: _Input, bounds: Bounds | None, outlet: _Outlet | None
) -> tuple[_Header | None, list[Diagnostic]]:
    if bounds is None:
        return None, [
            _unreachable(
                item,
                f"{item.value} is read only under bounds, and this call gives none. "
                "Give the hosts the call may reach.",
            )
        ]
    try:
        opened = fetch.vsicurl_path(item.value, bounds=bounds)
    except HydroModPyError as exc:
        return None, [_unreachable(item, getattr(exc, "message", "") or str(exc))]
    if not _is_raster(item):
        return None, []
    return _open(item, opened, outlet)


def _open(
    item: _Input, location: str, outlet: _Outlet | None
) -> tuple[_Header | None, list[Diagnostic]]:
    try:
        with rasterio.open(location) as source:
            header = _Header(
                crs=source.crs,
                transform=source.transform,
                nodata=source.nodata,
                outlet_fault=None if outlet is None else _outlet_fault(source, outlet, item),
            )
    except (OSError, rasterio.errors.RasterioError) as exc:
        return None, [_unreachable(item, f"{item.value} does not open as a raster: {exc}")]
    return header, [] if item.role == DEM_ROLE else _crs_fault(item, header)


def _crs_fault(item: _Input, header: _Header) -> list[Diagnostic]:
    if header.crs is not None or item.crs_fallback:
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


def _dem_faults(item: _Input, header: _Header) -> list[Diagnostic]:
    """Return the diagnostics of a DEM header that breaks the contract."""
    faults: list[str] = []
    transform = header.transform
    x_size, y_size = abs(transform.a), abs(transform.e)
    crs = header.crs
    if crs is not None and not (crs.is_projected and _in_metres(crs)):
        faults.append(
            f"its CRS {crs.to_string()} is not a projected CRS in metres. "
            "Reproject the file, or declare the CRS it was written in."
        )
    else:
        faults.extend(_contract_failures(x_size, y_size, crs))
    if transform.b != 0 or transform.d != 0:
        faults.append("its grid is rotated. Resample it on an axis-aligned grid.")
    if not math.isclose(x_size, y_size, rel_tol=SQUARE_PIXEL_TOLERANCE):
        faults.append(f"its pixel is not square ({x_size:g} by {y_size:g}).")
    diagnostics = [
        Diagnostic(
            path=item.path,
            code=BAD_HEADER,
            severity="error",
            detail=f"{item.value}: {fault}",
        )
        for fault in faults
    ]
    if header.outlet_fault is not None:
        diagnostics.append(
            Diagnostic(
                path=item.path, code=BAD_HEADER, severity="error", detail=header.outlet_fault
            )
        )
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


def _in_metres(crs: Any) -> bool:
    return str(crs.linear_units).lower() in {"metre", "meter", "m"}


def _contract_failures(x_size: float, y_size: float, crs: Any) -> list[str]:
    """Return what ``validate_dem`` refuses of a header without data: the CRS and the resolution."""
    try:
        validate_dem(
            {"resolution": (x_size, y_size), "crs": None if crs is None else crs.to_string()},
            DEMContract(),
        )
    except DataContractViolation as exc:
        return [str(failure) for failure in exc.context.get("failures", ())]
    return []


def _outlet_of(sections: Any) -> _Outlet | None:
    """Return the outlet the catchment is written with, or ``None`` when it has none."""
    geographic = getattr(sections, "geographic", None)
    catchment = getattr(geographic, "catchment", None)
    x = getattr(catchment, "x_outlet", None)
    y = getattr(catchment, "y_outlet", None)
    if x is None or y is None:
        return None
    return _Outlet(float(x), float(y), getattr(geographic, "crs_project", None) or None)


def _outlet_fault(source: Any, outlet: _Outlet, item: _Input) -> str | None:
    """Say what is wrong with the cell of the outlet, or return ``None`` when it holds a value.

    The outlet is written in ``[geographic] crs_project`` when that is set, else in
    the CRS of the DEM. The cell is read by a window of one pixel.
    """
    x, y = outlet.x, outlet.y
    if source.crs is None:
        return None
    if outlet.crs is not None:
        try:
            xs, ys = rasterio.warp.transform(
                rasterio.crs.CRS.from_user_input(outlet.crs), source.crs, [x], [y]
            )
        except (rasterio.errors.CRSError, ValueError):
            # The loader refuses a CRS it cannot read, with its own diagnostic.
            return None
        x, y = xs[0], ys[0]
    where = f"the outlet ({outlet.x:g}, {outlet.y:g})"
    row, col = source.index(x, y)
    if not (0 <= row < source.height and 0 <= col < source.width):
        return f"{where} falls outside {item.value}."
    window = Window(col, row, 1, 1)
    value = source.read(1, window=window)[0, 0]
    masked = source.read_masks(1, window=window)[0, 0] == 0
    if masked or np.isnan(value):
        return f"{where} falls on a cell of {item.value} that holds no value."
    return None
