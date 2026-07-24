"""Water-table elevation and depth helpers."""

from __future__ import annotations

import numpy as np
from flopy.utils import postprocessing as pp

from hydromodpy.core.nodata import SENTINEL_ABS_THRESHOLD

from ._models import NODATA


def compute_watertable_elevation(head: np.ndarray) -> np.ndarray:
    """Return the uppermost saturated layer head as a flat ``(ncpl,)`` array.

    flopy's ``get_water_table`` needs NAMED ``hdry`` / ``hnoflo`` arguments. The
    old positional call bound NODATA to ``hdry``, so genuinely dry cells (-1e30)
    were not masked and the function stopped descending to the saturated layer.
    The masked array is filled with NaN, then every masked / non-finite / sentinel
    cell maps to NODATA. Units: water-table elevation in metres on the DEM datum;
    -9999 marks an inactive or out-of-domain cell.
    """
    wt = pp.get_water_table(head, hdry=-1e30, hnoflo=1e30)
    wt = np.ma.filled(np.ma.asarray(wt), np.nan)
    wt = np.asarray(wt, dtype=float).reshape(-1)
    # The threshold catches both +1e30 (HNOFLO) and -1e30 (HDRY).
    missing = ~np.isfinite(wt) | (np.abs(wt) > SENTINEL_ABS_THRESHOLD)
    wt[missing] = float(NODATA)
    return wt


def compute_watertable_depth(
    *,
    watertable_elevation: np.ndarray,
    dem: np.ndarray,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """Compute depth to the water table on the solver cells (metres below DEM)."""
    elev = np.asarray(watertable_elevation, dtype=float).reshape(-1)
    dem_flat = np.asarray(dem, dtype=float).reshape(-1)
    mask = np.asarray(dem_mask, dtype=bool).reshape(-1)
    # A NODATA / non-finite elevation has no depth: keep NODATA, never subtract
    # it (that would yield a spurious ~10011 m depth).
    missing = mask | ~np.isfinite(elev) | (elev <= float(NODATA))
    depth = np.maximum(dem_flat - elev, 0.0)
    return np.where(missing, float(NODATA), depth)
