"""Analytical reference solution for the steady Dupuit fixed-head case."""

from __future__ import annotations

import numpy as np


def expected_dupuit_fixed_head_profile(
    *,
    x: np.ndarray,
    west_x: float,
    east_x: float,
    west_head: float,
    east_head: float,
) -> np.ndarray:
    """Return the steady Dupuit profile between heads held at ``west_x`` and ``east_x``."""
    fraction = (np.asarray(x, dtype=float) - float(west_x)) / (float(east_x) - float(west_x))
    return np.sqrt(
        float(west_head) ** 2 + (float(east_head) ** 2 - float(west_head) ** 2) * fraction
    )
