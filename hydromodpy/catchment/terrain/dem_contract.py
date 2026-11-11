"""The contract a DEM must hold before the terrain chain routes it.

``DEMContract`` carries the bounds of a digital elevation model and
``validate_dem`` applies them to an in-memory object. The pipeline and the
input check of a document hold a raster file to the same bounds through its
header and its outlet: ``read_dem_header`` reads only the header of an open
raster, and ``check_dem_header``, ``check_dem_outlet`` and ``check_dem_values``
refuse a raster that breaks one of them. The caller opens the file once.

The bounds are a declared projected CRS in metres, a grid that is not rotated, pixels
square within 1 % on the source header, a cell size from 1 to 250 m on the grid the
chain routes, elevations from -500 to 9000 m on the valid cells, and an outlet on a
valid cell. A DEM that fails one is refused with ``DataContractViolation`` (HMPY.E201).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from rasterio.io import DatasetReader
from rasterio.transform import rowcol

from hydromodpy.core.exceptions import DataContractViolation


@dataclass(frozen=True)
class DEMContract:
    """Declarative constraints for a digital elevation model."""

    min_resolution_m: float = 1.0
    max_resolution_m: float = 250.0
    min_elevation_m: float = -500.0
    max_elevation_m: float = 9000.0
    require_crs: bool = True


@dataclass(frozen=True, slots=True)
class DemHeader:
    """The facts of one DEM header the contract reads.

    ``crs`` is the CRS as a user-input string, ``None`` when the file declares
    none. ``projected`` and ``linear_unit`` describe it, and ``metric`` is True
    when one linear unit is one metre, whatever the unit is named. ``rotated`` is True
    when the geotransform has a rotation term, and ``dx_m`` and ``dy_m`` are the
    pixel sides the header declares. ``nodata`` is the value that marks a hole.
    """

    crs: str | None
    projected: bool
    linear_unit: str | None
    metric: bool
    rotated: bool
    dx_m: float
    dy_m: float
    nodata: float | None


def read_dem_header(src: DatasetReader) -> DemHeader:
    """Read the header of the open raster *src*, never its values."""
    crs_obj = src.crs
    transform = src.transform
    projected = bool(crs_obj is not None and crs_obj.is_projected)
    return DemHeader(
        crs=crs_obj.to_string() if crs_obj is not None else None,
        projected=projected,
        linear_unit=crs_obj.linear_units if crs_obj is not None else None,
        metric=projected and crs_obj.linear_units_factor[1] == 1.0,
        rotated=bool(transform.b != 0.0 or transform.d != 0.0),
        dx_m=float(abs(transform.a)),
        dy_m=float(abs(transform.e)),
        nodata=src.nodata,
    )


def check_dem_header(
    header: DemHeader,
    *,
    routing_res_m: float,
    contract: DEMContract | None = None,
) -> None:
    """Refuse a header the terrain chain cannot route.

    The CRS has to be declared, projected and in metres. The grid has to be
    square within 1 % and not rotated, and the resolution the chain routes,
    after the aggregation the configuration asks for, has to fall in the
    contract bounds. One refusal names every broken fact at once. The
    resolution is read in metres, so it is checked only under a projected CRS
    in metres.
    """
    contract = contract or DEMContract()
    failures: list[str] = []
    if header.crs in (None, ""):
        failures.append("The DEM declares no CRS.")
    else:
        if not header.metric:
            failures.append(
                f"The DEM CRS {header.crs!r} is not a projected CRS in metres, "
                f"its unit is {header.linear_unit!r}."
            )
        if header.rotated:
            failures.append(
                "The DEM grid is rotated, its geotransform has non-zero rotation terms."
            )
        if not _square_pixels(header.dx_m, header.dy_m):
            failures.append(
                f"The DEM pixels are not square, the header reads {header.dx_m:g} m by "
                f"{header.dy_m:g} m."
            )
    in_metres = header.crs in (None, "") or header.metric
    if in_metres and not contract.min_resolution_m <= routing_res_m <= contract.max_resolution_m:
        failures.append(
            f"The routed resolution {routing_res_m:g} m is outside "
            f"[{contract.min_resolution_m}, {contract.max_resolution_m}] m."
        )
    if failures:
        raise DataContractViolation("DEM header contract violated", failures=failures)


def check_dem_outlet(src: DatasetReader, header: DemHeader, x: float, y: float) -> None:
    """Refuse an outlet that is outside the open raster *src* or on a nodata cell.

    Only the cell the outlet falls on is read. A point outside the raster would
    otherwise be ignored silently by the snap of the catchment, and one on a
    nodata cell could not drain.
    """
    row, col = rowcol(src.transform, x, y)
    height, width = src.height, src.width
    failures: list[str] = []
    if not (0 <= row < height and 0 <= col < width):
        failures.append(
            f"The outlet ({x}, {y}) falls outside the DEM raster, which holds "
            f"{width} columns and {height} rows."
        )
    else:
        value = src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0]
        if header.nodata is not None and value == header.nodata:
            failures.append(f"The outlet ({x}, {y}) falls on a nodata cell, which holds no value.")
        elif not np.isfinite(value):
            failures.append(f"The outlet ({x}, {y}) falls on a cell that holds no value.")
    if failures:
        raise DataContractViolation("DEM outlet contract violated", failures=failures)


def check_dem_values(
    src: DatasetReader,
    header: DemHeader,
    contract: DEMContract | None = None,
) -> None:
    """Refuse an open DEM whose valid elevations leave the contract bounds.

    A declared nodata masks its cells, so a hole sentinel is never read as an
    elevation. Without a nodata every cell counts, and a sentinel such as -9999
    has to be declared as nodata.
    """
    contract = contract or DEMContract()
    values = np.asarray(src.read(1), dtype=float)
    if header.nodata is not None:
        values = np.where(values == header.nodata, np.nan, values)
    finite = np.isfinite(values)
    failures: list[str] = []
    if finite.any():
        vmin = float(np.nanmin(values[finite]))
        vmax = float(np.nanmax(values[finite]))
        if vmin < contract.min_elevation_m or vmax > contract.max_elevation_m:
            hint = (
                " A sentinel such as -9999 has to be declared as nodata."
                if header.nodata is None
                else ""
            )
            failures.append(
                f"The DEM elevation range [{vmin:.1f}, {vmax:.1f}] m is outside "
                f"[{contract.min_elevation_m}, {contract.max_elevation_m}] m.{hint}"
            )
    if failures:
        raise DataContractViolation("DEM values contract violated", failures=failures)


def validate_dem(
    dem: Any,
    contract: DEMContract | None = None,
    *,
    context: str | None = None,
) -> Any:
    """Validate an in-memory DEM against *contract*.

    Accepts ``xarray.DataArray`` / ``xarray.Dataset`` or a mapping with
    ``data``, ``resolution``, ``crs`` keys. Raises
    :class:`DataContractViolation` on any violation.
    """
    contract = contract or DEMContract()
    failures: list[str] = []

    crs = _get_attr(dem, "crs", "rio.crs")
    if contract.require_crs and crs in (None, ""):
        failures.append("DEM has no CRS declared.")

    resolution = _get_attr(dem, "resolution", "rio.resolution")
    res_val = _as_resolution(resolution)
    if res_val is None:
        failures.append("DEM resolution is not available.")
    elif not (contract.min_resolution_m <= res_val <= contract.max_resolution_m):
        failures.append(
            f"DEM resolution {res_val:.2f} m outside "
            f"[{contract.min_resolution_m}, {contract.max_resolution_m}]."
        )

    data = _get_data_array(dem)
    if data is not None:
        try:
            arr = np.asarray(data, dtype=float)
        except Exception:
            arr = None
        if arr is not None:
            if arr.ndim != 2:
                failures.append(f"DEM must be 2D, got shape {arr.shape}.")
            finite = np.isfinite(arr)
            if finite.any():
                vmin = float(np.nanmin(arr[finite]))
                vmax = float(np.nanmax(arr[finite]))
                if vmin < contract.min_elevation_m or vmax > contract.max_elevation_m:
                    failures.append(
                        f"DEM elevation range [{vmin:.1f}, {vmax:.1f}] m outside "
                        f"[{contract.min_elevation_m}, {contract.max_elevation_m}]."
                    )

    if failures:
        raise DataContractViolation(
            f"DEM contract violated{f' ({context})' if context else ''}",
            failures=failures,
        )
    return dem


def _square_pixels(dx_m: float, dy_m: float) -> bool:
    """Whether two pixel sides agree within 1 % of the larger one."""
    largest = max(dx_m, dy_m)
    return largest <= 0.0 or abs(dx_m - dy_m) <= 0.01 * largest


def _get_attr(obj: Any, *names: str) -> Any:
    for name in names:
        target = obj
        for part in name.split("."):
            if target is None:
                break
            target = getattr(target, part, None)
        if target is not None:
            return target
    if isinstance(obj, dict):
        return obj.get(names[0].split(".")[0])
    return None


def _as_resolution(resolution: Any) -> float | None:
    if resolution is None:
        return None
    try:
        if hasattr(resolution, "__iter__") and not isinstance(resolution, str):
            vals = [abs(float(v)) for v in resolution]
            return max(vals) if vals else None
        return abs(float(resolution))
    except (TypeError, ValueError):
        return None


def _get_data_array(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get("data")
    for attr in ("values", "to_numpy", "data"):
        target = getattr(obj, attr, None)
        if callable(target):
            try:
                return target()
            except TypeError:
                continue
        if target is not None:
            return target
    return None


__all__ = [
    "DEMContract",
    "DemHeader",
    "check_dem_header",
    "check_dem_outlet",
    "check_dem_values",
    "read_dem_header",
    "validate_dem",
]
