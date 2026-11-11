"""Shared nodata sentinels.

``RASTER_NODATA`` is the nodata value a raster carries in memory, and ``valid_cells`` is
the mask of the cells that hold a value. A new nodata convention is written here once,
never as a literal in a caller.
"""

from __future__ import annotations

import numpy as np

RASTER_NODATA = -9999.0

# MODFLOW dry / no-flow head sentinels (HDRY and HNOFLO, ~ +-1e30, plus the
# -6e30 some packages write) are finite, so they slip through an isfinite
# filter while sitting orders of magnitude above any physical head. A value
# whose magnitude exceeds this threshold is a sentinel, never a result.
SENTINEL_ABS_THRESHOLD = 1e20


def valid_cells(values: np.ndarray, nodata: float | None) -> np.ndarray:
    """Return the mask of the cells that hold a value.

    A cell holds a value when it is finite and differs from the *nodata*
    sentinel of its raster. A ``None`` or NaN sentinel leaves only the finite
    test.
    """
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    return valid


__all__ = [
    "RASTER_NODATA",
    "SENTINEL_ABS_THRESHOLD",
    "valid_cells",
]
