"""Averaging a forcing over the periods a coarse index stands for.

A stress period is a duration, not an instant. Reading the value nearest its
stamp reports one day as if it were the whole period, which is what inflated the
reported catchment discharge of the Nancon by 67 per cent above what its own
water balance allowed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.period_aggregation import period_mean_on_index


def _daily(start: str, days: int, values) -> pd.Series:
    return pd.Series(
        np.asarray(values, dtype="float64"),
        index=pd.date_range(start, periods=days, freq="D"),
    )


def test_a_period_gets_the_mean_of_its_days_not_the_nearest_one() -> None:
    # Thirty days, one of them ten times the others. Sampling the stamp would
    # return either 1 or 10; the period holds their mean.
    values = np.ones(30)
    values[0] = 10.0
    daily = _daily("2000-01-01", 30, values)
    monthly = pd.DatetimeIndex(["2000-01-15"])

    out = period_mean_on_index(daily, monthly)

    assert out.iloc[0] == pytest.approx(values.mean())


def test_each_period_reads_its_own_half_open_window() -> None:
    daily = _daily("2000-01-01", 60, np.concatenate([np.full(31, 2.0), np.full(29, 8.0)]))
    stamps = pd.DatetimeIndex(["2000-01-16", "2000-02-15"])

    out = period_mean_on_index(daily, stamps)

    assert out.iloc[0] == pytest.approx(2.0, abs=0.5)
    assert out.iloc[1] == pytest.approx(8.0, abs=0.5)


def test_a_period_with_no_sample_is_a_gap_not_a_zero() -> None:
    # A forcing that does not cover the run is something the caller has to see.
    daily = _daily("2000-01-01", 10, np.ones(10))
    stamps = pd.DatetimeIndex(["2000-01-05", "2005-01-05", "2010-01-05"])

    out = period_mean_on_index(daily, stamps)

    assert out.iloc[0] == pytest.approx(1.0)
    assert np.isnan(out.iloc[1])
    assert np.isnan(out.iloc[2])


def test_one_stamp_carries_no_spacing_so_the_whole_series_averages() -> None:
    daily = _daily("2000-01-01", 366, np.linspace(0.0, 2.0, 366))

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2001-01-01"]))

    assert out.iloc[0] == pytest.approx(1.0, abs=1e-9)
    assert len(out) == 1


def test_the_result_follows_the_order_of_the_index() -> None:
    daily = _daily("2000-01-01", 90, np.arange(90, dtype="float64"))
    stamps = pd.DatetimeIndex(["2000-03-15", "2000-01-15", "2000-02-15"])

    out = period_mean_on_index(daily, stamps)

    assert list(out.index) == list(stamps)
    assert out.iloc[0] > out.iloc[2] > out.iloc[1]


def test_an_empty_forcing_is_all_gaps() -> None:
    stamps = pd.DatetimeIndex(["2000-01-15", "2000-02-15"])

    out = period_mean_on_index(pd.Series(dtype="float64"), stamps)

    assert out.isna().all()
    assert list(out.index) == list(stamps)


def test_a_naive_index_and_an_aware_forcing_still_align() -> None:
    daily = _daily("2000-01-01", 30, np.ones(30)).tz_localize("UTC")

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2000-01-15"]))

    assert out.iloc[0] == pytest.approx(1.0)
