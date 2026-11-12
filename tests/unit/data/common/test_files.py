"""Tests for common/files."""

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.common.files import read_locations_csv, read_timeseries_csv


class TestReadLocationsCSV:
    def test_missing_id_raises(self, tmp_path):
        csv_path = tmp_path / "loc.csv"
        pd.DataFrame({"x": [1], "y": [2]}).to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="missing id column"):
            read_locations_csv(csv_path)


class TestReadTimeseriesCSV:
    def test_custom_columns(self, tmp_path):
        csv_path = tmp_path / "ts.csv"
        pd.DataFrame(
            {
                "date": ["2020-01-01"],
                "debit": [3.14],
            }
        ).to_csv(csv_path, index=False)

        df = read_timeseries_csv(csv_path, col_datetime="date", col_value="debit")
        assert df["value"].iloc[0] == pytest.approx(3.14)

    def test_missing_datetime_raises(self, tmp_path):
        csv_path = tmp_path / "ts.csv"
        pd.DataFrame({"value": [1]}).to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="missing datetime column"):
            read_timeseries_csv(csv_path)
