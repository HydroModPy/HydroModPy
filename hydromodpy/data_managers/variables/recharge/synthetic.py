"""Synthetic recharge generation.

Generates recharge time series from inline values, with optional
sinusoidal modulation.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.variables.recharge.config import RechargeSourceConfig


def generate(
    config: RechargeSourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[PointRecord]:
    """Generate synthetic recharge from config values.

    Returns a list with a single PointRecord containing the synthetic series.
    """
    values = [float(v) for v in config.values]

    # Determine time index
    if project_period is not None:
        freq = config.freq or "D"
        index = pd.date_range(start=project_period[0], end=project_period[1], freq=freq)
    elif config.start_date:
        freq = config.freq or "D"
        periods = config.periods or len(values)
        index = pd.date_range(start=config.start_date, periods=periods, freq=freq)
    else:
        freq = config.freq or "D"
        periods = config.periods or len(values)
        index = pd.date_range(start="2000-01-01", periods=periods, freq=freq)

    # Broadcast values to match index length
    if len(values) == 1:
        series_values = np.full(len(index), values[0])
    elif len(values) == len(index):
        series_values = np.array(values)
    else:
        # Repeat or truncate values to match index length
        series_values = np.resize(np.array(values), len(index))

    # Apply sinusoidal modulation if specified
    if config.amplitude is not None and config.period_days is not None:
        offset = config.offset if config.offset is not None else 0.0
        t = np.arange(len(index), dtype=float)
        omega = 2.0 * np.pi / config.period_days
        modulation = config.amplitude * np.sin(omega * t) + offset
        series_values = series_values + modulation

    df = pd.DataFrame({
        "datetime": index,
        "value": series_values,
    })

    return [
        PointRecord(
            station_id="synthetic",
            variable="recharge",
            source="synthetic",
            unit="mm/day",
            frequency=freq,
            data=df,
            date_start=index[0].to_pydatetime(),
            date_end=index[-1].to_pydatetime(),
            location=None,
            is_constant=(len(set(series_values)) == 1),
        )
    ]
