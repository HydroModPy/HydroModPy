"""Averaging a forcing over the periods a coarse index stands for.

A stress period is a duration, not an instant. Reading the value nearest its
stamp reports one day as if it were the whole period, which is what inflated the
reported catchment discharge of the Nancon by 67 per cent above what its own
water balance allowed.

A stamp is the END of its period, as the solvers write it: January 2000 of a
monthly run is stamped 2000-02-01. These tests used to read a stamp as the
center of a period reaching halfway to its neighbors; they were rewritten when
that reading was found to compare January with mid-December to mid-January.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import build_simulation_time_boundaries
from hydromodpy.core.time.period_aggregation import (  # noqa: E402
    first_period_step,
    naive_timestamp,
    observation_step,
    observed_on_periods,
    period_edges,
    period_end_stamps,
    period_mean_on_index,
    period_point_on_index,
    period_value_on_index,
    periods_in_window,
    runoff_m3_s_on_index,
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


RUNOFF_AREA_M2 = 86.4e6


TWO_THEN_FIVE = _daily("2000-01-01", 20, [2.0] * 10 + [5.0] * 10)


STAMP_11 = pd.Timestamp("2000-01-11")


STAMP_21 = pd.Timestamp("2000-01-21")


@pytest.mark.parametrize(
    ("index", "start", "expected"),
    [
        (pd.DatetimeIndex([STAMP_11, STAMP_21]), None, [2.0, 5.0]),
        # Aware in UTC, the first stamp is the start once both are read in UTC: it is ignored.
        (pd.DatetimeIndex([STAMP_11, STAMP_21], tz="UTC"), STAMP_11, [2.0, 5.0]),
        # The window start bounds the first period.
        (pd.DatetimeIndex([STAMP_21]), STAMP_11, [5.0]),
        # A start on the stamp bounds nothing: the mean of the whole forcing.
        (pd.DatetimeIndex([STAMP_21]), STAMP_21, [3.5]),
        # A period the forcing misses is a gap.
        (pd.DatetimeIndex([STAMP_21, "2000-01-31"]), None, [5.0, np.nan]),
        # Nothing to convert.
        (pd.DatetimeIndex([]), STAMP_11, []),
    ],
)
def test_a_runoff_becomes_a_discharge_on_the_periods(index, start, expected) -> None:
    out = runoff_m3_s_on_index(TWO_THEN_FIVE, index, area_m2=RUNOFF_AREA_M2, start=start)

    assert out.index.equals(index)
    np.testing.assert_array_equal(out.to_numpy(), expected)


@pytest.mark.parametrize("area_m2", [0.0, -1.0])
def test_a_runoff_without_a_positive_area_is_refused(area_m2) -> None:
    with pytest.raises(ValueError, match=f"must be positive, got {area_m2} m2"):
        runoff_m3_s_on_index(TWO_THEN_FIVE, [STAMP_11], area_m2=area_m2)


def test_a_runoff_over_less_than_a_square_metre_is_still_a_discharge() -> None:
    out = runoff_m3_s_on_index(TWO_THEN_FIVE, [STAMP_21], area_m2=0.5, start=STAMP_11)

    np.testing.assert_allclose(out.to_numpy(), [5.0 * 1e-3 * 0.5 / 86400.0], rtol=1e-12)


def test_a_naive_timestamp_is_read_in_utc():
    aware = pd.Timestamp("2020-01-01 02:00", tz="Europe/Paris")
    assert naive_timestamp(aware) == pd.Timestamp("2020-01-01 01:00")
    assert naive_timestamp("2020-01-01") == pd.Timestamp("2020-01-01")


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        (["2020-01-01"], None),
        (["2020-01-01", "2020-03-01"], pd.DateOffset(months=2)),
        (["2020-01-01", "2020-01-04"], pd.Timedelta(days=3)),
        (["2020-01-01", "2020-01-31"], pd.Timedelta(days=30)),
        (["2020-01-01", "2020-01-02", "2020-01-03"], pd.offsets.Day(1)),
    ],
)
def test_the_first_period_step_is_a_calendar_step_when_stamps_allow_it(stamps, expected):
    assert first_period_step(pd.to_datetime(stamps)) == expected


def test_the_edges_of_nothing_or_of_one_stamp_without_start_are_refused():
    with pytest.raises(ValueError, match="empty index"):
        period_edges(pd.DatetimeIndex([]))
    with pytest.raises(ValueError, match="single stamp"):
        period_edges(pd.to_datetime(["2020-02-01"]))


_STAMPS = pd.date_range("2020-01-02", "2020-01-10", freq="D")  # end stamps, period i = day i


@pytest.mark.parametrize(
    ("method", "start", "end", "kept"),
    [
        # a mean counts when its whole period [s, e) lies in the window
        ("mean", "2020-01-04", "2020-01-08", ["01-05", "01-06", "01-07", "01-08", "01-09"]),
        ("mean", None, "2020-01-03", ["01-02", "01-03", "01-04"]),
        ("mean", "2020-01-09", None, ["01-10"]),
        # a state counts when its stamp falls on a day of the window
        ("point", "2020-01-04", "2020-01-06", ["01-04", "01-05", "01-06"]),
        ("point", None, None, [s.strftime("%m-%d") for s in _STAMPS]),
    ],
)
def test_a_window_of_days_keeps_whole_periods_for_a_mean_and_stamps_for_a_state(
    method, start, end, kept
):
    flags = periods_in_window(_STAMPS, method=method, start=start, end=end)
    assert [s.strftime("%m-%d") for s in _STAMPS[flags]] == kept


def test_a_period_that_cannot_be_placed_is_outside_a_window_with_a_start():
    one = pd.to_datetime(["2020-02-01"])
    assert not periods_in_window(one, method="mean", start="2020-01-01").any()
    assert periods_in_window(
        one, method="mean", period_start="2020-01-01", start="2020-01-01"
    ).all()
    assert periods_in_window(one, method="mean").all()


def test_an_empty_stamp_list_keeps_nothing():
    flags = periods_in_window(pd.DatetimeIndex([]), method="mean", start="2020-01-01")
    assert flags.size == 0


def test_a_missing_stamp_does_not_move_the_start_of_the_next_period():
    grid = pd.date_range("2020-01-02", "2020-01-10", freq="D")
    kept = grid.delete(2)  # 01-04 is missing from the data
    flags = periods_in_window(kept, method="mean", start="2020-01-04", grid=grid)
    assert [s.strftime("%m-%d") for s in kept[flags]] == [
        "01-05",
        "01-06",
        "01-07",
        "01-08",
        "01-09",
        "01-10",
    ]


def test_the_fallback_stamps_a_whole_number_of_years_in_calendar_years():
    ends = period_end_stamps("2000-01-01", "2002-01-01", 2, step_unit="year")
    assert ends.tolist() == [pd.Timestamp("2001-01-01"), pd.Timestamp("2002-01-01")]


def test_the_fallback_with_no_period_is_empty_and_with_an_uneven_fit_splits_evenly():
    assert len(period_end_stamps("2000-01-01", "2000-02-01", 0)) == 0
    ends = period_end_stamps("2000-01-01", "2000-01-11", 5, step_unit="day")
    assert (ends[1:] - ends[:-1]).unique().tolist() == [pd.Timedelta(days=2)]
    assert ends[-1] == pd.Timestamp("2000-01-11")


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        (["2020-01-01", "2020-02-01"], None),
        (["2020-01-01", "2020-02-01", "2020-03-01"], pd.offsets.MonthBegin(1)),
        (["2020-01-15", "2020-02-15", "2020-04-15"], pd.DateOffset(months=1)),
        (["2020-01-01", "2020-01-02", "2020-01-05"], pd.Timedelta(days=2)),
    ],
    ids=["two-samples", "regular-months", "gap-keeps-month", "irregular-days"],
)
def test_the_step_of_a_chronicle_is_its_calendar_frequency_or_median_spacing(stamps, expected):
    assert observation_step(pd.to_datetime(stamps)) == expected


_ENDS = pd.date_range("2020-01-02", "2020-01-06", freq="D")


def test_a_daily_observation_lands_on_the_day_its_stamp_closes():
    obs = _daily("2020-01-01", 5, [1, 2, 3, 4, 5])
    out = period_value_on_index(obs, _ENDS)
    assert out.tolist() == [1, 2, 3, 4, 5]


def test_a_monthly_observation_holds_over_the_days_it_stands_for_and_a_gap_stays_nan():
    obs = pd.Series([10.0, 30.0], index=pd.to_datetime(["2020-01-01", "2020-03-01"]))
    obs.loc[pd.Timestamp("2020-02-01")] = 20.0
    obs = obs.sort_index()
    days = pd.date_range("2020-01-02", "2020-04-02", freq="D")
    out = period_value_on_index(obs, days)
    assert out.loc["2020-01-20"] == 10.0  # held from 2020-01-01
    assert out.loc["2020-03-10"] == 30.0
    assert np.isnan(out.loc["2020-04-02"])  # reach of March ended 2020-04-01
    assert out.dropna().between(10.0, 30.0).all()


def test_one_period_without_start_takes_the_whole_chronicle_only_when_it_reaches_the_stamp():
    obs = _daily("2020-01-01", 4, [1, 2, 3, 6])
    reaches = period_value_on_index(obs, pd.to_datetime(["2020-01-05"]))
    assert reaches.iloc[0] == pytest.approx(3.0)
    too_old = period_value_on_index(obs, pd.to_datetime(["2030-01-05"]))
    assert too_old.isna().all()


def test_an_empty_chronicle_is_all_gaps_for_every_rule():
    empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
    for rule in (period_value_on_index, period_point_on_index):
        assert rule(empty, _ENDS).isna().all()


def test_a_state_finer_than_the_run_is_averaged_around_the_stamp():
    # hourly state read at a daily stamp: mean of the samples within +-12 h
    hours = pd.date_range("2020-01-01", "2020-01-04", freq="h", inclusive="left")
    obs = pd.Series(np.arange(len(hours), dtype=float), index=hours)
    stamps = pd.to_datetime(["2020-01-02", "2020-01-03"])
    out = period_point_on_index(obs, stamps)
    assert out.iloc[0] == pytest.approx(np.arange(12, 36).mean())


def test_a_state_as_coarse_as_the_run_takes_the_nearest_sample_within_tolerance():
    obs = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01", "2020-01-03"]))
    stamps = pd.DatetimeIndex(["2020-01-02", "2020-01-03 06:00", "2020-01-04 12:00"])
    out = period_point_on_index(obs, stamps)
    assert out.iloc[0] == 1.0  # tie, earlier sample wins
    assert out.iloc[1] == 2.0
    assert np.isnan(out.iloc[2])  # 1.5 d from the nearest sample, beyond the 1.25 d spacing
    wide = period_point_on_index(obs, stamps, tolerance=pd.Timedelta(days=40))
    assert wide.iloc[2] == 2.0


def test_a_single_stamp_is_read_with_the_spacing_of_the_chronicle():
    obs = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01", "2020-01-03"]))
    assert period_point_on_index(obs, pd.to_datetime(["2020-01-03"])).iloc[0] == 2.0
    single = pd.Series([4.0], index=pd.to_datetime(["2020-01-01"]))
    assert period_point_on_index(single, pd.to_datetime(["2020-01-01"])).iloc[0] == 4.0
    assert np.isnan(period_point_on_index(single, pd.to_datetime(["2020-01-02"])).iloc[0])


def test_observed_on_periods_chooses_the_rule_by_time_method():
    obs = _daily("2020-01-01", 5, [1, 2, 3, 4, 5])
    mean = observed_on_periods(obs, _ENDS, method="mean")
    point = observed_on_periods(obs, _ENDS, method="point")
    assert mean.tolist() == [1, 2, 3, 4, 5]
    assert point.tolist() == [2, 3, 4, 5, 5]
    with pytest.raises(ValueError):
        observed_on_periods(obs, _ENDS, method="median")


# A window of days keeps a period when it holds the whole period, a state at its stamp.
#
# The run and the calibration session read the same declared window. The run
# kept a mean over a period when the whole period ``[s, e)`` lay inside it; the
# session kept a pair when its END stamp did, so it scored the period before the
# window and lost the last one (N1 of the audit of 2026-10-20). One rule now
# serves both, written once in ``core/time``.


FIRST_PERIOD = pd.Timestamp("2000-01-01")


STAMPS = pd.date_range("2000-02-01", "2003-01-01", freq="MS")


def _kept(mask: np.ndarray, stamps: pd.DatetimeIndex = STAMPS) -> pd.DatetimeIndex:
    return stamps[np.asarray(mask, dtype=bool)]


def test_a_mean_counts_when_its_whole_period_lies_in_the_window() -> None:
    mask = periods_in_window(
        STAMPS,
        method="mean",
        start=datetime.date(2001, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )

    kept = _kept(mask)
    assert len(kept) == 24
    # January 2001 closes on 2001-02-01, December 2002 on 2003-01-01.
    assert kept[0] == pd.Timestamp("2001-02-01")
    assert kept[-1] == pd.Timestamp("2003-01-01")


def test_a_start_alone_keeps_what_the_two_bounds_keep_on_a_run_that_ends_there() -> None:
    mask = periods_in_window(
        STAMPS, method="mean", start=pd.Timestamp("2001-01-01"), period_start=FIRST_PERIOD
    )

    assert len(_kept(mask)) == 24


def test_an_end_alone_keeps_every_period_closed_by_midnight_after_it() -> None:
    mask = periods_in_window(STAMPS, method="mean", end=pd.Timestamp("2000-12-31"))

    kept = _kept(mask)
    assert len(kept) == 12
    assert kept[-1] == pd.Timestamp("2001-01-01")


def test_a_period_straddling_a_bound_is_out() -> None:
    mask = periods_in_window(
        STAMPS,
        method="mean",
        start=datetime.date(2001, 1, 15),
        end=datetime.date(2001, 3, 15),
        period_start=FIRST_PERIOD,
    )

    assert list(_kept(mask)) == [pd.Timestamp("2001-03-01")]


def test_a_state_counts_when_its_stamp_falls_in_the_window() -> None:
    mask = periods_in_window(
        STAMPS, method="point", start=datetime.date(2001, 1, 1), end=datetime.date(2002, 12, 31)
    )

    kept = _kept(mask)
    assert len(kept) == 24
    assert kept[0] == pd.Timestamp("2001-01-01")
    assert kept[-1] == pd.Timestamp("2002-12-01")


def test_a_gap_in_the_pairs_does_not_move_the_start_of_the_next_period() -> None:
    # February 2001 is missing from the pairs: March 2001 still starts on 1 March.
    paired = STAMPS.delete(STAMPS.get_loc(pd.Timestamp("2001-03-01")))

    mask = periods_in_window(
        paired,
        method="mean",
        start=datetime.date(2001, 3, 1),
        end=datetime.date(2001, 3, 31),
        grid=STAMPS,
        period_start=FIRST_PERIOD,
    )

    assert list(_kept(mask, paired)) == [pd.Timestamp("2001-04-01")]


def test_a_steady_stamp_counts_when_its_period_lies_in_the_window() -> None:
    stamp = pd.DatetimeIndex([pd.Timestamp("2003-01-01")])

    inside = periods_in_window(
        stamp,
        method="mean",
        start=datetime.date(2000, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )
    cut = periods_in_window(
        stamp, method="mean", start=datetime.date(2001, 1, 1), period_start=FIRST_PERIOD
    )

    assert inside.tolist() == [True]
    assert cut.tolist() == [False]


def test_utc_stamps_are_read_on_the_naive_utc_clock() -> None:
    aware = STAMPS.tz_localize("UTC")

    mask = periods_in_window(
        aware,
        method="mean",
        start=datetime.date(2001, 1, 1),
        end=datetime.date(2002, 12, 31),
        period_start=FIRST_PERIOD,
    )

    assert int(np.count_nonzero(mask)) == 24


def test_no_bound_keeps_everything() -> None:
    mask = periods_in_window(STAMPS, method="mean")

    assert bool(np.all(mask))
