"""Which samples a stress period takes from a forcing record, and when it is covered."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.coverage import calendar_sample_days, enforce_coverage, samples_by_period


def _days(start: str, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D")


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


def test_a_single_sample_has_equal_weights():
    assert calendar_sample_days(pd.to_datetime(["2020-01-01"])) is None


def test_a_record_going_back_in_time_has_equal_weights():
    stamps = pd.to_datetime(["2020-03-01", "2020-01-01", "2020-02-01"])
    assert calendar_sample_days(stamps) is None


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


def _uncovered_periods(n_late: int):
    stamps = _days("2020-01-01", 2)
    edges = pd.date_range("2020-01-03", periods=n_late + 1, freq="10D")
    return samples_by_period(stamps, edges), edges


def test_an_unknown_policy_is_refused_even_when_all_is_covered():
    ps, edges = _uncovered_periods(1)
    with pytest.raises(ValueError, match="coverage_policy must be one of"):
        enforce_coverage(ps, edges, policy="strict", label="recharge")


def test_the_warn_policy_warns_once():
    ps, edges = _uncovered_periods(1)
    with pytest.warns(UserWarning, match="nearest sample"):
        enforce_coverage(ps, edges, policy="warn", label="recharge")


def test_the_message_lists_five_periods_and_counts_the_others():
    ps, edges = _uncovered_periods(8)
    with pytest.raises(ValueError, match="and 3 more:"):
        enforce_coverage(ps, edges, policy="error", label="recharge")
