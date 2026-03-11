"""Numeric metrics used by analytical validation comparisons."""

from __future__ import annotations

import numpy as np


def rmse(actual, expected) -> float:
    """Return the root mean square error between two numeric arrays."""
    actual_arr = np.asarray(actual, dtype=float)
    expected_arr = np.asarray(expected, dtype=float)
    return float(np.sqrt(np.mean((actual_arr - expected_arr) ** 2)))


def max_abs_error(actual, expected) -> float:
    """Return the maximum absolute deviation between two numeric arrays."""
    actual_arr = np.asarray(actual, dtype=float)
    expected_arr = np.asarray(expected, dtype=float)
    return float(np.max(np.abs(actual_arr - expected_arr)))


def mean_along_axis(values, *, axis: int) -> np.ndarray:
    """Average one array along the requested axis."""
    return np.asarray(values, dtype=float).mean(axis=int(axis))


def max_std_along_axis(values, *, axis: int) -> float:
    """Return the maximum standard deviation along the requested axis."""
    return float(np.max(np.std(np.asarray(values, dtype=float), axis=int(axis))))
