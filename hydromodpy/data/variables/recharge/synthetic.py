"""Synthetic recharge generation.

Generates recharge time series from inline values, with optional
sinusoidal modulation.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset
from pandas.tseries.offsets import MonthEnd, QuarterEnd, YearEnd

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.data.managers.base_manager_common import SourceContext

# Calendar offsets whose pandas date_range stamps land on the period end.
_PERIOD_END_OFFSETS = (MonthEnd, QuarterEnd, YearEnd)


def _synthetic_index(
    freq: str,
    *,
    start: object,
    end: object | None = None,
    periods: int | None = None,
) -> pd.DatetimeIndex:
    """Return the sample stamps of a synthetic series.

    A forcing sample is stamped at the START of the period it averages, the
    convention the stress-period alignment reads. ``pd.date_range`` with an
    end-anchored alias ('ME', 'QE', 'YE') stamps the period end instead: one
    'YE' value for 2020 would land on 2020-12-31 and leave January to
    November with no value. Those aliases are stamped at their period start.
    """
    offset = to_offset(freq)
    if isinstance(offset, _PERIOD_END_OFFSETS):
        if end is not None:
            spans = pd.period_range(start=start, end=end, freq=offset)
        else:
            spans = pd.period_range(start=start, periods=periods, freq=offset)
        return pd.DatetimeIndex(spans.start_time)
    if end is not None:
        return pd.date_range(start=start, end=end, freq=freq)
    return pd.date_range(start=start, periods=periods, freq=freq)


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
    freq = config.freq or "D"
    if project_period is not None:
        index = _synthetic_index(freq, start=project_period[0], end=project_period[1])
    else:
        periods = config.periods or len(values)
        start = config.start_date or "2000-01-01"
        index = _synthetic_index(freq, start=start, periods=periods)

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

    df = pd.DataFrame(
        {
            "datetime": index,
            "value": series_values,
        }
    )

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


def fetch(
    cfg: RechargeSourceConfig,
    *,
    bbox: tuple | None,
    period: tuple[datetime, datetime] | None,
    context: SourceContext,
) -> list[PointRecord]:
    """The ``SOURCES`` entry of ``source = "synthetic"``: a series built from the section."""
    del bbox, context
    return generate(cfg, project_period=period)
