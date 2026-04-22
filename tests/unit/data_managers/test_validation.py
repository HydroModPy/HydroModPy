"""Tests for common/validation."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.common.validation import check_required_columns, compute_completeness


class TestComputeCompleteness:
    def test_complete_series(self):
        dates = pd.date_range("2020-01-01", "2020-01-10", freq="D")
        df = pd.DataFrame({"datetime": dates, "value": range(10)})
        result = compute_completeness(
            df,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 10),
            station_id="S1",
        )
        assert result["completeness_pct"] == pytest.approx(100.0)
        assert result["missing_days"] == 0
        assert result["gaps_detected"] == 0

    def test_missing_days(self):
        # 10 days expected, only 8 present (skip day 3 and 7)
        dates = pd.to_datetime(
            [
                "2020-01-01",
                "2020-01-02",
                "2020-01-04",
                "2020-01-05",
                "2020-01-06",
                "2020-01-08",
                "2020-01-09",
                "2020-01-10",
            ]
        )
        df = pd.DataFrame({"datetime": dates, "value": range(8)})
        result = compute_completeness(
            df,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 10),
            station_id="S1",
        )
        assert result["missing_days"] == 2
        assert result["gaps_detected"] == 2

    def test_empty_df(self):
        result = compute_completeness(
            pd.DataFrame(),
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 10),
            station_id="S1",
        )
        assert result["missing_days"] == 10

    def test_no_dates_returns_empty(self):
        result = compute_completeness(pd.DataFrame(), station_id="S1")
        assert result["expected_days"] == 0


class TestCheckRequiredColumns:
    def test_ok(self):
        df = pd.DataFrame({"datetime": [1], "value": [2]})
        check_required_columns(df, ("datetime", "value"))

    def test_missing(self):
        df = pd.DataFrame({"datetime": [1]})
        with pytest.raises(ValueError, match="Missing required columns"):
            check_required_columns(df, ("datetime", "value"))
