"""Unit tests for LTTB downsampling of dense time series.

Covers ``hydromodpy.results.derive.downsample``:
- threshold detection
- LTTB reduces a dense series to ``n_out`` points
- the algorithm preserves boundary samples
- ``n_out`` >= len(series) returns the original series
- fallback implementation produces consistent output
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive import downsample as tsd


def _dense_series(n: int, *, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed=seed)
    index = pd.date_range("2020-01-01", periods=n, freq="15min")
    values = rng.normal(loc=10.0, scale=2.5, size=n)
    return pd.Series(values, index=index, name="discharge")


def test_should_downsample_default_threshold() -> None:
    assert tsd.should_downsample(60_000) is True
    assert tsd.should_downsample(10_000) is False


def test_lttb_1M_points_to_5000() -> None:
    series = _dense_series(1_000_000)
    out = tsd.lttb_downsample(series, n_out=5_000)
    assert len(out) == 5_000
    # First and last samples are preserved by LTTB.
    assert out.index[0] == series.index[0]
    assert out.index[-1] == series.index[-1]
    assert np.isfinite(out.values).all()


def test_downsample_none_returns_full_series() -> None:
    """When n_out >= len(series), the algorithm must not lose information."""
    series = _dense_series(2_500)
    out = tsd.lttb_downsample(series, n_out=5_000)
    assert len(out) == len(series)
    assert (out.values == series.values).all()


def test_lttb_rejects_invalid_n_out() -> None:
    series = _dense_series(100)
    with pytest.raises(ValueError):
        tsd.lttb_downsample(series, n_out=2)


def test_lttb_fallback_matches_pure_numpy_path() -> None:
    """The pure-numpy fallback path must work when lttb is unavailable."""
    series = _dense_series(20_000)
    points = np.column_stack([np.arange(len(series), dtype=float), series.values])
    out = tsd._lttb_fallback(points, 1000)
    assert out.shape == (1000, 2)
    # Boundary points preserved.
    assert (out[0] == points[0]).all()
    assert (out[-1] == points[-1]).all()


def test_lttb_preserves_index_type() -> None:
    series = _dense_series(80_000)
    out = tsd.lttb_downsample(series, n_out=2_000)
    assert isinstance(out.index, pd.DatetimeIndex)
    assert len(out) == 2_000
