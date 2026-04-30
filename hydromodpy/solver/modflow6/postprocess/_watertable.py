"""Water-table elevation and depth helpers."""

from __future__ import annotations

import numpy as np
from flopy.utils import postprocessing as pp

from ._models import NODATA


def compute_watertable_elevation(head: np.ndarray) -> np.ndarray:
    """Extract the top water table as one flat `(ncpl,)` array."""
    wt = pp.get_water_table(head, NODATA)
    wt = np.asarray(wt, dtype=float).reshape(-1)
    wt[np.isnan(wt)] = NODATA
    wt[wt <= -1e20] = NODATA
    return wt


def compute_watertable_depth(
    *,
    watertable_elevation: np.ndarray,
    dem: np.ndarray,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """Compute depth to the water table on the solver cells."""
    return np.where(
        np.asarray(dem_mask, dtype=bool).reshape(-1),
        float(NODATA),
        np.maximum(
            np.asarray(dem, dtype=float).reshape(-1)
            - np.asarray(watertable_elevation, dtype=float).reshape(-1),
            0.0,
        ),
    )
