"""Averaging a forcing over the periods a coarse index stands for.

A stress period is a duration, not an instant. Reading the value nearest its
stamp reports one day as if it were the whole period, which is what inflated the
reported catchment discharge of the Nancon by 67 per cent above what its own
water balance allowed.

A stamp is the END of its period, as the solvers write it: January 2000 of a
monthly run is stamped 2000-02-01. These tests used to read a stamp as the
centre of a period reaching halfway to its neighbours; they were rewritten when
that reading was found to compare January with mid-December to mid-January.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import build_simulation_time_boundaries
from hydromodpy.core.time.period_aggregation import (
    first_period_step,
    period_edges,
    period_end_stamps,
    period_mean_on_index,
)


def _daily(start: str, days: int, values) -> pd.Series:
    return pd.Series(
        np.asarray(values, dtype="float64"),
        index=pd.date_range(start, periods=days, freq="D"),
    )


def _day_number(start: str, days: int) -> pd.Series:
    """Daily series worth its own day number, 0 on ``start``."""
    return _daily(start, days, np.arange(days))


MONTH_ENDS_2000 = pd.date_range("2000-02-01", "2001-01-01", freq="MS")


def test_a_monthly_run_reads_the_calendar_month_its_stamp_closes() -> None:
    # Daily values equal to the day number since 2000-01-01. The mean over a
    # month is the mean of its first and last day numbers, in closed form.
    # January is days 0..30, February of the leap year 2000 is days 31..59.
    daily = _day_number("2000-01-01", 366)

    out = period_mean_on_index(daily, MONTH_ENDS_2000)

    first_days = pd.date_range("2000-01-01", "2000-12-01", freq="MS")
    last_days = MONTH_ENDS_2000.shift(-1, freq="D")
    origin = pd.Timestamp("2000-01-01")
    expected = [((a - origin).days + (b - origin).days) / 2 for a, b in zip(first_days, last_days)]
    assert out.tolist() == pytest.approx(expected, abs=1e-12)
    assert out.iloc[0] == pytest.approx(15.0)
    assert out.iloc[1] == pytest.approx(45.0)


def test_the_window_start_and_the_inferred_start_agree_on_a_regular_run() -> None:
    daily = _day_number("2000-01-01", 366)

    inferred = period_mean_on_index(daily, MONTH_ENDS_2000)
    given = period_mean_on_index(daily, MONTH_ENDS_2000, start="2000-01-01")

    assert inferred.tolist() == pytest.approx(given.tolist(), abs=1e-12)


def test_a_leap_february_holds_its_twenty_ninth_day() -> None:
    # 29 on 29 February, zero elsewhere. February 2000 has 29 days, so its
    # mean is exactly 1; January and March stay zero.
    values = np.zeros(91)
    values[59] = 29.0
    daily = _daily("2000-01-01", 91, values)

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"]))

    assert out.tolist() == pytest.approx([0.0, 1.0, 0.0])


def test_a_monthly_chronicle_stamped_at_its_month_start_passes_unchanged() -> None:
    qmm = pd.Series(np.arange(1.0, 13.0), index=pd.date_range("2000-01-01", periods=12, freq="MS"))

    out = period_mean_on_index(qmm, MONTH_ENDS_2000)

    assert out.tolist() == qmm.tolist()


def test_a_daily_run_reads_the_day_its_stamp_closes() -> None:
    # A daily run stamps day d at d + 1; a daily chronicle stamps it at d.
    daily = _day_number("2000-01-01", 10)
    stamps = pd.date_range("2000-01-02", periods=10, freq="D")

    out = period_mean_on_index(daily, stamps)

    assert out.tolist() == daily.tolist()


def test_one_yearly_steady_period_averages_its_own_year() -> None:
    # Three years of daily values worth their year. The period [2000, 2001)
    # holds exactly the 366 days of 2000.
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    daily = pd.Series(index.year.astype("float64"), index=index)

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2001-01-01"]), start="2000-01-01")

    assert out.iloc[0] == 2000.0


def test_one_stamp_without_a_start_averages_the_whole_series() -> None:
    daily = _daily("2000-01-01", 366, np.linspace(0.0, 2.0, 366))

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2001-01-01"]))

    assert out.iloc[0] == pytest.approx(1.0, abs=1e-9)
    assert len(out) == 1


def test_a_steady_spin_up_before_monthly_periods_needs_its_start() -> None:
    # One steady year, then three months. The stamps alone cannot tell the
    # spin-up lasted a year, so the window start is passed.
    index = pd.date_range("1999-01-01", "2000-03-31", freq="D")
    daily = pd.Series(np.where(index.year == 1999, 7.0, index.month.astype("float64")), index=index)
    stamps = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    out = period_mean_on_index(daily, stamps, start="1999-01-01")

    assert out.tolist() == [7.0, 1.0, 2.0, 3.0]


def test_a_steady_first_month_of_a_monthly_run_is_january() -> None:
    # The steady first period of a monthly run is the first calendar month,
    # stamped at its end like every other period.
    daily = _daily("2000-01-01", 60, np.concatenate([np.full(31, 2.0), np.full(29, 8.0)]))
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01"])

    out = period_mean_on_index(daily, stamps)

    assert out.tolist() == [2.0, 8.0]


def test_a_period_with_no_sample_is_a_gap_not_a_zero() -> None:
    # A forcing that does not cover the run is something the caller has to see.
    daily = _daily("2000-01-01", 31, np.ones(31))
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])

    out = period_mean_on_index(daily, stamps)

    assert out.iloc[0] == pytest.approx(1.0)
    assert np.isnan(out.iloc[1])
    assert np.isnan(out.iloc[2])


def test_the_result_follows_the_order_of_the_index() -> None:
    daily = _daily("2000-01-01", 91, np.arange(91, dtype="float64"))
    stamps = pd.DatetimeIndex(["2000-04-01", "2000-02-01", "2000-03-01"])

    out = period_mean_on_index(daily, stamps)

    assert list(out.index) == list(stamps)
    assert out.iloc[0] > out.iloc[2] > out.iloc[1]


def test_an_empty_forcing_is_all_gaps() -> None:
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01"])

    out = period_mean_on_index(pd.Series(dtype="float64"), stamps)

    assert out.isna().all()
    assert list(out.index) == list(stamps)


def test_a_naive_index_and_an_aware_forcing_still_align() -> None:
    daily = _daily("2000-01-01", 31, np.ones(31)).tz_localize("UTC")

    out = period_mean_on_index(daily, pd.DatetimeIndex(["2000-02-01", "2000-03-01"]))

    assert out.iloc[0] == pytest.approx(1.0)


def test_a_millisecond_index_from_parquet_aligns() -> None:
    # Timestamps read back from Parquet come in milliseconds.
    daily = _daily("2000-01-01", 31, np.ones(31))
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01"]).as_unit("ms")

    out = period_mean_on_index(daily, stamps)

    assert out.iloc[0] == pytest.approx(1.0)


def test_the_edges_are_the_time_grid_boundaries() -> None:
    # The solvers stamp boundaries[1:]. Reading those stamps back has to give
    # the boundaries the launcher built, the first one included.
    window = SimpleNamespace(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2002-12-31"),
        step_value=1,
        step_unit="month",
        period_bounds=None,
    )
    boundaries = pd.DatetimeIndex(build_simulation_time_boundaries(window))

    edges = period_edges(boundaries[1:])

    assert edges.equals(boundaries.as_unit("ns"))


def test_a_first_spacing_of_whole_months_is_a_calendar_month() -> None:
    step = first_period_step(pd.DatetimeIndex(["2000-03-15", "2000-04-15"]))

    assert pd.Timestamp("2000-03-15") - step == pd.Timestamp("2000-02-15")


def test_a_start_after_the_first_stamp_is_refused() -> None:
    with pytest.raises(ValueError, match="not before its end stamp"):
        period_edges(pd.DatetimeIndex(["2000-02-01"]), start="2000-02-01")


def test_the_catalog_fallback_stamps_calendar_month_ends() -> None:
    stamps = period_end_stamps("2000-01-01", "2003-01-01", 36, step_unit="month")

    assert stamps.equals(pd.date_range("2000-02-01", "2003-01-01", freq="MS").as_unit("ns"))


def test_the_catalog_fallback_splits_a_daily_window_evenly() -> None:
    stamps = period_end_stamps("2000-01-01", "2000-01-11", 10, step_unit="day")

    assert stamps.equals(pd.date_range("2000-01-02", "2000-01-11", freq="D").as_unit("ns"))


def test_the_catalog_fallback_of_one_period_is_the_window_end() -> None:
    stamps = period_end_stamps("2000-01-01", "2003-01-01", 1, step_unit="month")

    assert list(stamps) == [pd.Timestamp("2003-01-01")]
