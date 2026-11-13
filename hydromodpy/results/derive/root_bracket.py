"""The final bracket of a root search: the closest pair of values around a sign change."""

from __future__ import annotations

import numpy as np


def sign_changes(value: np.ndarray, residual: np.ndarray) -> list[tuple[float, float]]:
    """Return each pair of neighbouring values whose residuals change sign.

    The values are sorted first. A pair with a residual that is zero or not finite is no
    sign change.
    """
    value, residual = np.asarray(value, float), np.asarray(residual, float)
    keep = np.isfinite(value) & np.isfinite(residual)
    order = np.argsort(value[keep])
    value, residual = value[keep][order], residual[keep][order]
    flips = np.flatnonzero(residual[:-1] * residual[1:] < 0)
    return [(float(value[i]), float(value[i + 1])) for i in flips]


def final_bracket(value: np.ndarray, residual: np.ndarray) -> tuple[float, float] | None:
    """Return the narrowest pair of neighbouring values whose residuals change sign.

    Narrow is the factor between the two ends, which is what a search over a ratio halves.
    The values are positive. None when the residual never changes sign.
    """
    pairs = sign_changes(value, residual)
    return min(pairs, key=lambda pair: pair[1] / pair[0]) if pairs else None


def closing_root(value: np.ndarray, residual: np.ndarray) -> float | None:
    """Return the end of the final bracket whose residual is the smaller, else None.

    It is the root a search on one bound closes on.
    """
    bracket = final_bracket(value, residual)
    if bracket is None:
        return None
    value, residual = np.asarray(value, float), np.asarray(residual, float)
    low, high = (float(abs(residual[value == end][0])) for end in bracket)
    return bracket[0] if low <= high else bracket[1]
