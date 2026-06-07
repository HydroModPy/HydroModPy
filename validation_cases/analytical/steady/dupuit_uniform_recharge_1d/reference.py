"""Analytical reference solution for the Dupuit 1D uniform-recharge case."""

from __future__ import annotations

import numpy as np

SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


def mm_day_to_m_s(value: float) -> float:
    """Convert a recharge rate from mm/day to m/s."""
    return float(value) / MM_PER_M / SECONDS_PER_DAY


def expected_dupuit_uniform_recharge_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head: float,
    east_head: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the steady Dupuit profile with uniform recharge and fixed heads."""
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    length = float(xmax) - float(xmin)
    local_x = x - float(xmin)
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    head_squared = (
        float(west_head) ** 2
        + ((float(east_head) ** 2 - float(west_head) ** 2) * (local_x / length))
        + (recharge_m_per_s / float(hydraulic_conductivity_m_per_s)) * local_x * (length - local_x)
    )
    return np.sqrt(head_squared)
