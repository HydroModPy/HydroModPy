"""Temporal alignment helpers for forcing series.

Provides stress-period aggregation for any datetime-indexed series
against a simulation time window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow


def _align_series_to_simulation_window(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str,
) -> pd.Series:
    """Aggregate one datetime-indexed series to simulation stress periods.

    Aggregation policy
    ------------------
    - One output value per stress period.
    - Value = arithmetic mean over values in [period_start, period_end).
    - If no value falls in a period, reuse the last available value before
      period_end (forward carry).
    """
    from hydromodpy.core.time import build_simulation_time_boundaries

    if series.empty:
        raise ValueError(f"{label} series is empty and cannot be aligned to simulation.time.")

    data = series.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)
    data = data.sort_index()

    boundaries = build_simulation_time_boundaries(simulation_window)
    starts = pd.DatetimeIndex(boundaries[:-1])
    values: list[float] = []
    for left, right in zip(boundaries[:-1], boundaries[1:], strict=False):
        chunk = data.loc[(data.index >= left) & (data.index < right)]
        if not chunk.empty:
            values.append(float(chunk.mean()))
            continue

        # No value inside this period: carry the latest known value before the
        # period end so solver forcing remains continuous.
        history = data.loc[data.index < right]
        if history.empty:
            raise ValueError(
                f"{label} has no value available before simulation period ending at {right}."
            )
        values.append(float(history.iloc[-1]))

    return pd.Series(values, index=starts, dtype=float)


def align_forcing_series_to_simulation_window(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str = "forcing",
) -> pd.Series:
    """Public wrapper for period aggregation on simulation-time boundaries."""
    return _align_series_to_simulation_window(
        series,
        simulation_window=simulation_window,
        label=label,
    )
