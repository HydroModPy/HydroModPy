"""Which samples a stress period takes from a forcing record, and when it is covered."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.coverage import (
    calendar_sample_days,
    enforce_coverage,
    record_step,
    samples_by_period,
)


def _days(start: str, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D")


# ---------------------------------------------------------------- calendar weights


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        (pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]), [31, 29, 31]),
        (pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31"]), [31, 29, 31]),
        (pd.to_datetime(["2019-01-01", "2020-01-01", "2021-01-01"]), [365, 366, 365]),
    ],
    ids=["month-start", "month-end", "year-start"],
)
def test_a_monthly_or_yearly_record_weighs_each_sample_by_its_calendar_length(stamps, expected):
    assert calendar_sample_days(stamps).tolist() == expected


@pytest.mark.parametrize(
    "stamps",
    [
        pd.to_datetime(["2020-01-01"]),
        pd.to_datetime(["2020-01-01", "2020-01-05", "2020-01-09"]),
        pd.to_datetime(["2020-01-01", "2020-04-01", "2020-07-01"]),
    ],
    ids=["one-sample", "irregular-days", "quarterly"],
)
def test_any_other_record_has_equal_weights(stamps):
    assert calendar_sample_days(stamps) is None


def test_a_record_going_back_in_time_has_equal_weights():
    stamps = pd.to_datetime(["2020-03-01", "2020-01-01", "2020-02-01"])
    assert calendar_sample_days(stamps) is None


def test_the_step_of_a_record_is_the_median_spacing_and_none_for_one_sample():
    stamps = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-10"])
    assert record_step(stamps) == pd.Timedelta(days=1)
    assert record_step(stamps[:1]) is None


# ------------------------------------------------------------ samples by period


def test_a_period_takes_the_samples_stamped_inside_it_half_open():
    stamps = _days("2020-01-01", 6)
    edges = pd.to_datetime(["2020-01-01", "2020-01-03", "2020-01-05", "2020-01-07"])
    ps = samples_by_period(stamps, edges)
    assert [i.tolist() for i in ps.inside] == [[0, 1], [2, 3], [4, 5]]
    assert ps.uncovered == ()
    assert ps.weights is None


def test_the_mean_of_a_period_is_the_mean_of_its_samples_and_stays_within_their_range():
    stamps = _days("2020-01-01", 4)
    edges = pd.to_datetime(["2020-01-01", "2020-01-05"])
    ps = samples_by_period(stamps, edges)
    values = np.array([1.0, 2.0, 3.0, 10.0])
    got = ps.value_of(values, 0)
    assert got == pytest.approx(4.0)
    assert values.min() <= got <= values.max()


def test_a_calendar_record_averages_by_month_length():
    stamps = pd.to_datetime(["2020-01-01", "2020-02-01"])
    edges = pd.to_datetime(["2020-01-01", "2020-03-01"])
    ps = samples_by_period(stamps, edges)
    got = ps.value_of(np.array([0.0, 29.0]), 0)
    assert got == pytest.approx((0.0 * 31 + 29.0 * 29) / 60)


def test_a_single_sample_in_a_calendar_period_is_returned_as_is():
    stamps = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    edges = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"])
    ps = samples_by_period(stamps, edges)
    assert ps.value_of(np.array([5.0, 7.0, 9.0]), 1) == 7.0


def test_a_period_without_sample_takes_the_latest_earlier_one_and_is_covered():
    stamps = pd.to_datetime(["2020-01-01", "2020-01-11"])  # step 10 d: last sample to Jan 21
    edges = pd.to_datetime(["2020-01-01", "2020-01-05", "2020-01-08", "2020-01-12"])
    ps = samples_by_period(stamps, edges)
    assert ps.fill[1] == 0
    assert ps.uncovered == ()
    assert ps.value_of(np.array([3.0, 8.0]), 1) == 3.0


def test_a_period_before_the_first_stamp_is_uncovered_and_takes_the_first_sample():
    stamps = _days("2020-01-10", 3)
    edges = pd.to_datetime(["2020-01-01", "2020-01-10", "2020-01-13"])
    ps = samples_by_period(stamps, edges)
    assert ps.uncovered == (0,)
    assert ps.value_of(np.array([4.0, 5.0, 6.0]), 0) == 4.0


def test_a_period_after_the_last_step_is_uncovered_and_takes_the_last_sample():
    stamps = _days("2020-01-01", 3)  # last sample stands for Jan 3 only
    edges = pd.to_datetime(["2020-01-01", "2020-01-04", "2020-01-10", "2020-01-20"])
    ps = samples_by_period(stamps, edges)
    assert ps.uncovered == (1, 2)
    assert ps.value_of(np.array([4.0, 5.0, 6.0]), 2) == 6.0


def test_a_one_sample_record_stands_for_all_later_time():
    edges = pd.to_datetime(["2020-01-01", "2021-01-01", "2030-01-01"])
    ps = samples_by_period(pd.to_datetime(["2020-01-01"]), edges)
    assert ps.uncovered == ()


def test_microsecond_stamps_compare_with_nanosecond_edges():
    stamps = pd.DatetimeIndex(["2020-01-01", "2020-01-02"]).as_unit("us")
    edges = pd.DatetimeIndex(["2020-01-01", "2020-01-03"]).as_unit("ns")
    assert [i.tolist() for i in samples_by_period(stamps, edges).inside] == [[0, 1]]


@pytest.mark.parametrize(
    ("stamps", "match"),
    [
        (pd.DatetimeIndex([]), "at least one sample"),
        (pd.to_datetime(["2020-01-02", "2020-01-01"]), "must be sorted"),
    ],
)
def test_an_empty_or_unsorted_record_is_refused(stamps, match):
    with pytest.raises(ValueError, match=match):
        samples_by_period(stamps, pd.to_datetime(["2020-01-01", "2020-01-05"]))


# --------------------------------------------------------------------- policy


def _uncovered_periods(n_late: int):
    stamps = _days("2020-01-01", 2)
    edges = pd.date_range("2020-01-03", periods=n_late + 1, freq="10D")
    return samples_by_period(stamps, edges), edges


def test_an_unknown_policy_is_refused_even_when_all_is_covered():
    ps, edges = _uncovered_periods(1)
    with pytest.raises(ValueError, match="coverage_policy must be one of"):
        enforce_coverage(ps, edges, policy="strict", label="recharge")


def test_the_error_policy_stops_the_run_and_names_the_periods():
    ps, edges = _uncovered_periods(2)
    with pytest.raises(
        ValueError, match=r"recharge does not cover stress period\(s\) 0 \[2020-01-03"
    ):
        enforce_coverage(ps, edges, policy="error", label="recharge")


def test_the_warn_policy_warns_once():
    ps, edges = _uncovered_periods(1)
    with pytest.warns(UserWarning, match="nearest sample"):
        enforce_coverage(ps, edges, policy="warn", label="recharge")


def test_the_message_lists_five_periods_and_counts_the_others():
    ps, edges = _uncovered_periods(8)
    with pytest.raises(ValueError, match="and 3 more:"):
        enforce_coverage(ps, edges, policy="error", label="recharge")


def test_the_ignore_policy_and_full_coverage_say_nothing(recwarn):
    ps, edges = _uncovered_periods(2)
    enforce_coverage(ps, edges, policy="ignore", label="recharge")
    covered = samples_by_period(
        _days("2020-01-01", 5), pd.to_datetime(["2020-01-01", "2020-01-04"])
    )
    enforce_coverage(
        covered, pd.to_datetime(["2020-01-01", "2020-01-04"]), policy="error", label="x"
    )
    assert len(recwarn) == 0
