"""Analytical reference solution for the steady Dupuit fixed-head case."""

from __future__ import annotations

import numpy as np


def expected_dupuit_fixed_head_profile(
    *,
    xmin: float,
    xmax: float,
    ncol: int,
    west_head: float,
    east_head: float,
) -> np.ndarray:
    """Return the steady Dupuit profile between two imposed heads."""
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    return np.sqrt(
        float(west_head) ** 2
        + (
            (float(east_head) ** 2 - float(west_head) ** 2)
            * ((x - float(xmin)) / float(xmax - xmin))
        )
    )
