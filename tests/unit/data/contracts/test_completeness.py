"""Completeness of a daily series: expected, present and missing days over a period."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.completeness import compute_completeness

START = datetime(2020, 1, 1)


def series(n_days):
    dates = pd.date_range("2020-01-01", periods=n_days, freq="D")
    return pd.DataFrame({"datetime": dates, "value": range(n_days)})


def test_complete_series():
    result = compute_completeness(
        series(10), start_date=START, end_date=datetime(2020, 1, 10), station_id="S1"
    )

    assert result["completeness_pct"] == pytest.approx(100.0)
    assert result["missing_days"] == 0
    assert result["gaps_detected"] == 0


def test_series_with_gaps():
    # 20 records over a 30-day period.
    result = compute_completeness(
        series(20), start_date=START, end_date=datetime(2020, 1, 30), station_id="S1"
    )

    assert result["expected_days"] == 30
    assert result["actual_days"] == 20
    assert result["missing_days"] == 10
    assert result["completeness_pct"] == pytest.approx(66.67, rel=0.01)


def test_empty_series():
    result = compute_completeness(
        pd.DataFrame(), start_date=START, end_date=datetime(2020, 1, 10), station_id="S1"
    )

    assert result["missing_days"] == 10


def test_no_dates_expects_nothing():
    assert compute_completeness(pd.DataFrame(), station_id="S1")["expected_days"] == 0
