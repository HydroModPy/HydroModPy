"""Stress-period bounds of a simulation window."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow

__all__ = ["stress_period_bounds"]


def stress_period_bounds(
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]] | None:
    """Return (start, end) bounds for each stress period, or None."""
    if simulation_window is None:
        return None

    explicit_bounds = getattr(simulation_window, "period_bounds", None)
    if explicit_bounds is not None:
        bounds = []
        for raw_start, raw_end in tuple(explicit_bounds)[: int(nper)]:
            bounds.append((pd.Timestamp(raw_start), pd.Timestamp(raw_end)))
        return bounds or None

    from hydromodpy.core.time import build_simulation_time_boundaries

    boundaries = build_simulation_time_boundaries(simulation_window)
    if len(boundaries) < 2:
        return None

    bounds = []
    for i in range(min(nper, len(boundaries) - 1)):
        bounds.append((boundaries[i], boundaries[i + 1]))
    return bounds
