"""LTTB downsampling for dense time series stored in the catalog.

The Largest Triangle Three Buckets algorithm preserves visual fidelity
while reducing point count. Used by :meth:`Run.timeseries` when callers
pass ``downsample="lttb"`` and the series exceeds the activation
threshold.

Original values stay reachable via ``downsample=None`` (or by not
passing the argument).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_TIMESERIES_THRESHOLD: int = 50_000
DEFAULT_TARGET_POINTS: int = 5_000


def is_lttb_available() -> bool:
    """Return True when the optional ``lttb`` package is importable."""
    try:
        import lttb  # noqa: F401
    except ImportError:
        return False
    return True


def should_downsample(n_points: int, *, threshold: int = DEFAULT_TIMESERIES_THRESHOLD) -> bool:
    """Return True when the series exceeds the LTTB activation threshold."""
    return int(n_points) > int(threshold)


def lttb_downsample(
    series: pd.Series,
    *,
    n_out: int = DEFAULT_TARGET_POINTS,
) -> pd.Series:
    """Return an LTTB-downsampled view of ``series`` with at most ``n_out`` points.

    The series index is preserved (DatetimeIndex or numeric). When
    ``len(series) <= n_out``, the original series is returned untouched.
    """
    n = len(series)
    if n_out <= 2:
        raise ValueError("n_out must be at least 3 for LTTB")
    if n <= n_out:
        return series

    values = np.asarray(series.values, dtype=float)
    index = series.index
    x_numeric = _index_to_numeric(index)

    points = np.column_stack([x_numeric, values])
    sampled = _run_lttb(points, n_out)

    sampled_idx_numeric = sampled[:, 0]
    sampled_values = sampled[:, 1]

    sampled_index = _numeric_to_index(sampled_idx_numeric, index)
    return pd.Series(sampled_values, index=sampled_index, name=series.name)


def _run_lttb(points: np.ndarray, n_out: int) -> np.ndarray:
    """Invoke ``lttb`` when present, fall back to a local implementation."""
    if is_lttb_available():
        import lttb

        return np.asarray(lttb.downsample(points, n_out=int(n_out)))
    return _lttb_fallback(points, int(n_out))


def _lttb_fallback(points: np.ndarray, n_out: int) -> np.ndarray:
    """Pure-numpy LTTB. Mirrors Sveinn Steinarsson's reference algorithm."""
    n = points.shape[0]
    if n <= n_out:
        return points
    bucket_size = (n - 2) / (n_out - 2)
    sampled = np.empty((n_out, 2), dtype=points.dtype)
    sampled[0] = points[0]
    sampled[-1] = points[-1]
    a = 0
    for i in range(n_out - 2):
        start = int(np.floor((i + 1) * bucket_size)) + 1
        end = int(np.floor((i + 2) * bucket_size)) + 1
        end = min(end, n)
        bucket_x = points[start:end, 0]
        bucket_y = points[start:end, 1]
        next_start = end
        next_end = int(np.floor((i + 3) * bucket_size)) + 1
        next_end = min(next_end, n)
        if next_start >= n:
            avg_x = points[-1, 0]
            avg_y = points[-1, 1]
        else:
            avg_x = float(points[next_start:next_end, 0].mean())
            avg_y = float(points[next_start:next_end, 1].mean())
        ax_, ay_ = points[a, 0], points[a, 1]
        area = np.abs((ax_ - avg_x) * (bucket_y - ay_) - (ax_ - bucket_x) * (avg_y - ay_)) * 0.5
        chosen = int(np.argmax(area))
        sampled[i + 1] = points[start + chosen]
        a = start + chosen
    return sampled


def _index_to_numeric(index: pd.Index) -> np.ndarray:
    if isinstance(index, pd.DatetimeIndex):
        return index.asi8.astype(float)
    return np.asarray(index, dtype=float)


def _numeric_to_index(values: np.ndarray, original: pd.Index) -> pd.Index:
    if isinstance(original, pd.DatetimeIndex):
        return pd.DatetimeIndex(values.astype("int64"))
    return pd.Index(values)


__all__ = [
    "DEFAULT_TARGET_POINTS",
    "DEFAULT_TIMESERIES_THRESHOLD",
    "is_lttb_available",
    "lttb_downsample",
    "should_downsample",
]
