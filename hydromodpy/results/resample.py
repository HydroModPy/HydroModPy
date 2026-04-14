"""Temporal resampling utilities for simulation results.

Placeholder module for future resampling functionality.
Provides sub-daily → daily and daily → monthly aggregations
for time series and spatial fields stored in the SimulationCatalog.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resample_timeseries():
    """Resample time series to a coarser frequency.

    .. note::
       Not yet implemented. Will support daily/monthly/yearly
       aggregation with configurable statistics (mean, sum, min, max).
    """
    raise NotImplementedError("resample_timeseries is planned but not yet implemented")


def resample_field():
    """Resample spatial fields to a coarser time frequency.

    .. note::
       Not yet implemented.
    """
    raise NotImplementedError("resample_field is planned but not yet implemented")
