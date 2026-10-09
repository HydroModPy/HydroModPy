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

    A period takes the mean of the samples stamped in ``[start, end)``. A period
    with none takes the sample in force, and a period the record does not cover
    follows ``simulation.time.coverage_policy``
    (:mod:`hydromodpy.core.time.coverage`).
    """
    from hydromodpy.core.time import build_simulation_time_boundaries
    from hydromodpy.core.time.coverage import enforce_coverage, samples_by_period

    if series.empty:
        raise ValueError(f"{label} series is empty and cannot be aligned to simulation.time.")

    data = series.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)
    data = data.sort_index()

    boundaries = build_simulation_time_boundaries(simulation_window)
    starts = pd.DatetimeIndex(boundaries[:-1])
    periods = samples_by_period(data.index, boundaries)
    enforce_coverage(
        periods,
        boundaries,
        policy=str(getattr(simulation_window, "coverage_policy", "error")),
        label=label,
    )
    samples = data.to_numpy(dtype=float)
    values = [
        float(samples[inside].mean()) if inside.size else float(samples[int(fill)])
        for inside, fill in zip(periods.inside, periods.fill, strict=True)
    ]
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
