"""Analytical reference solution for the Dupuit 1D divide-river case."""

from __future__ import annotations

import numpy as np


SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


def mm_day_to_m_s(value: float) -> float:
    """Convert a recharge rate from mm/day to m/s."""
    return float(value) / MM_PER_M / SECONDS_PER_DAY


def expected_dupuit_divide_river_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    river_head: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the steady Dupuit profile with west-side divide and east-side river."""
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    length = float(xmax) - float(xmin)
    local_x = x - float(xmin)
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    head_squared = (
        float(river_head) ** 2
        + (recharge_m_per_s / float(hydraulic_conductivity_m_per_s))
        * (length**2 - local_x**2)
    )
    return np.sqrt(head_squared)
