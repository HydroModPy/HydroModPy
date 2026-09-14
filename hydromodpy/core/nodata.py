"""Shared nodata sentinels."""

from __future__ import annotations

RASTER_NODATA = -9999.0
RESULTS_NODATA = -99999.0
EXTREME_NODATA = -999999.0

NODATA_SENTINELS = (RASTER_NODATA, RESULTS_NODATA, EXTREME_NODATA)

# MODFLOW dry / no-flow head sentinels (HDRY and HNOFLO, ~ +-1e30, plus the
# -6e30 some packages write) are finite, so they slip through an isfinite
# filter while sitting orders of magnitude above any physical head. A value
# whose magnitude exceeds this threshold is a sentinel, never a result.
SENTINEL_ABS_THRESHOLD = 1e20

__all__ = [
    "EXTREME_NODATA",
    "NODATA_SENTINELS",
    "RASTER_NODATA",
    "RESULTS_NODATA",
    "SENTINEL_ABS_THRESHOLD",
]
