"""Contract for DEM rasters (DEMs are not DataFrames, hence a custom check).

The contract is intentionally light: it asserts that the payload is a
2D grid with a declared CRS and a resolution no finer than 1 metre. The
underlying storage format (xarray, rasterio, numpy) is not prescribed —
we accept any object exposing the attributes we need.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import DataContractViolation


@dataclass(frozen=True)
class DEMContract:
    """Declarative constraints for a digital elevation model."""

    min_resolution_m: float = 1.0
    max_resolution_m: float = 250.0
    min_elevation_m: float = -500.0
    max_elevation_m: float = 9000.0
    require_crs: bool = True


def validate_dem(
    dem: Any,
    contract: DEMContract | None = None,
    *,
    context: str | None = None,
) -> Any:
    """Validate a DEM against *contract*.

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
    for attr in ("values", "to_numpy", "data"):
        target = getattr(obj, attr, None)
        if callable(target):
            try:
                return target()
            except TypeError:
                continue
        if target is not None:
            return target
    if isinstance(obj, dict):
        return obj.get("data")
    return None
