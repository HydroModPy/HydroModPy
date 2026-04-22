"""Pure-function derivations of secondary fields from primary outputs.

The functions here turn primary fields (head, surface elevation, drain
budget) into the quantities needed by figures and exports — water-table
elevation, depth, seepage masks, fluxes. They never read the catalog
directly: callers pass in numpy or xarray arrays and receive arrays back.

This keeps display code free of physics: a figure asks for a derived field
already computed; the catalog or the extractor is responsible for invoking
these helpers when ingesting solver output.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

ArrayLike = np.ndarray | xr.DataArray

__all__ = [
    "fluxes_from_budget",
    "seepage_mask",
    "watertable_depth",
    "watertable_elevation",
]


def watertable_elevation(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Water-table elevation — head clipped to the surface elevation.

    ``head`` is an N-D array shaped ``(..., n_cells)`` (or ``(n_layers, n_cells)``
    for multilayer models). ``top`` is a per-cell surface array.
    """
    if isinstance(head, xr.DataArray):
        wt = head.where(head <= top, top)
        wt.attrs.update(units="m", long_name="Water-table elevation")
        return wt
    head_arr = np.asarray(head, dtype=float)
    top_arr = np.asarray(top, dtype=float)
    if head_arr.ndim == 2 and head_arr.shape[1] == top_arr.size:
        # Multilayer: pick uppermost saturated head per cell.
        wt = np.full(head_arr.shape[1], np.nan, dtype=float)
        for layer in range(head_arr.shape[0]):
            mask = np.isfinite(head_arr[layer]) & np.isnan(wt)
            wt[mask] = head_arr[layer, mask]
        return np.minimum(wt, top_arr)
    return np.minimum(head_arr, top_arr)


def watertable_depth(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Depth from surface to water table, clipped to ≥ 0."""
    if isinstance(head, xr.DataArray):
        depth = (top - head).where((top - head) >= 0, 0.0)
        depth.attrs.update(units="m", long_name="Depth to water table")
        return depth
    wt = watertable_elevation(head, top)
    top_arr = np.asarray(top, dtype=float)
    return np.maximum(top_arr - wt, 0.0)


def seepage_mask(head: ArrayLike, top: ArrayLike) -> ArrayLike:
    """Boolean cells where the water table reaches or exceeds the surface."""
    if isinstance(head, xr.DataArray):
        return (head >= top).astype("int8")
    wt = watertable_elevation(head, top)
    return (np.asarray(wt) >= np.asarray(top)).astype("int8")


def fluxes_from_budget(
    component_field: ArrayLike,
    cell_area: ArrayLike,
) -> ArrayLike:
    """Convert a per-cell budget flux (m³/d) into a unit flux (m/d).

    Negative values are out-of-aquifer fluxes (e.g. drains); positive values
    are inflow. Cells with zero area pass through as NaN.
    """
    if isinstance(component_field, xr.DataArray):
        area = xr.DataArray(np.asarray(cell_area, dtype=float))
        flux = component_field / area.where(area > 0)
        flux.attrs.update(units="m d-1", long_name="Cell-averaged flux")
        return flux
    field = np.asarray(component_field, dtype=float)
    area = np.asarray(cell_area, dtype=float)
    out = np.full_like(field, np.nan, dtype=float)
    valid = area > 0
    out[..., valid] = field[..., valid] / area[valid]
    return out
