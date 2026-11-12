"""Point record: a daily series (datetime, value) of one station, cut to a period."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.timeseries import PointRecord


def daily_record(n_days=30, **kwargs):
    return PointRecord(
        station_id="S1",
        variable="discharge",
        source="file",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", periods=n_days, freq="D"),
                "value": range(n_days),
            }
        ),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, n_days),
        **kwargs,
    )


def test_filter_by_period():
    record = daily_record(source_unit="L/s")

    filtered = record.filter_by_period(datetime(2020, 1, 5), datetime(2020, 1, 15))

    assert filtered.n_records == 11  # 5th to 15th inclusive
    assert filtered.source_unit == "L/s"


def test_filter_recomputes_quality():
    filtered = daily_record().filter_by_period(datetime(2020, 1, 1), datetime(2020, 1, 10))

    assert filtered.quality["n_expected"] == 10
    assert filtered.quality["completeness_pct"] == 100.0


def test_missing_columns_are_refused():
    data = pd.DataFrame({"date": ["2020-01-01"], "val": [1.0]})

    with pytest.raises(ValueError, match="missing columns"):
        PointRecord(
            station_id="S1",
            variable="x",
            source="x",
            unit="x",
            frequency="D",
            data=data,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 1),
        )
