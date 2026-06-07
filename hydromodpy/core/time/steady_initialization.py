"""Temporal helpers for same-solver steady-state initializations."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.core.time import build_simulation_time_boundaries


def _positive_period_lengths_seconds(source_time_grid: object) -> np.ndarray:
    source_periods = getattr(source_time_grid, "period_lengths_seconds", None)
    if source_periods is None:
        source_periods = ()
    raw_periods = np.asarray(source_periods, dtype=float).reshape(-1)
    return raw_periods[np.isfinite(raw_periods) & (raw_periods > 0.0)]


def _source_boundaries(source_time_grid: object) -> tuple[object, ...]:
    boundaries = getattr(source_time_grid, "boundaries", None)
    if boundaries is not None and len(boundaries) >= 2:
        return tuple(boundaries)

    window = getattr(source_time_grid, "window", None)
    if window is None:
        return ()
    try:
        return tuple(build_simulation_time_boundaries(window))
    except Exception:
        return ()


def single_period_mean_forcing_time_grid(source_time_grid: object) -> SimpleNamespace:
    """Return a one-period grid whose forcing window spans the source grid."""
    positive_periods = _positive_period_lengths_seconds(source_time_grid)
    period_length = float(np.sum(positive_periods)) if positive_periods.size else 1.0

    source_window = getattr(source_time_grid, "window", None)
    mean_window = None
    boundaries = _source_boundaries(source_time_grid)
    if source_window is not None and len(boundaries) >= 2:
        mean_window = SimpleNamespace(
            start=getattr(source_window, "start", boundaries[0]),
            end=getattr(source_window, "end", boundaries[-1]),
            step_value=getattr(source_window, "step_value", 1),
            step_unit=getattr(source_window, "step_unit", "day"),
            period_bounds=((boundaries[0], boundaries[-1]),),
            coverage_policy=getattr(source_window, "coverage_policy", "ignore"),
        )
    elif source_window is not None:
        mean_window = source_window

    return SimpleNamespace(
        period_lengths_seconds=np.asarray([period_length], dtype=float),
        nstp_per_period=1,
        window=mean_window,
        boundaries=() if len(boundaries) < 2 else (boundaries[0], boundaries[-1]),
    )


__all__ = ["single_period_mean_forcing_time_grid"]
