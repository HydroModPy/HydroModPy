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
    x: np.ndarray,
    divide_x: float,
    river_x: float,
    river_head: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
) -> np.ndarray:
    """Return the steady Dupuit profile between a divide and a held river head.

    The no-flow divide sits at ``divide_x`` (the west face) and the river head
    at ``river_x``, where the model holds it.
    """
    length = float(river_x) - float(divide_x)
    local_x = np.asarray(x, dtype=float) - float(divide_x)
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    head_squared = float(river_head) ** 2 + (
        recharge_m_per_s / float(hydraulic_conductivity_m_per_s)
    ) * (length**2 - local_x**2)
    return np.sqrt(head_squared)
