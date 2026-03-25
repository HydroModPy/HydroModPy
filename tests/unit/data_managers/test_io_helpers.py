"""Tests for common/io_helpers."""

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.common.io_helpers import (
    parse_chronicle_filename,
    parse_loc_filename,
    read_locations_csv,
    read_timeseries_csv,
    safe_file_token,
)


class TestFilenameConventions:
    def test_parse_chronicle(self):
        parts = parse_chronicle_filename("hydrometry_custom_ST001_20200101_20201231_D.csv")
        assert parts["type"] == "hydrometry"
        assert parts["source"] == "custom"
        assert parts["id"] == "ST001"
        assert parts["start"] == "20200101"
        assert parts["end"] == "20201231"
        assert parts["freq"] == "D"

    def test_parse_chronicle_complex_id(self):
        # BSS id "07548X0009/F" → safe_file_token → "07548X0009_F"
        # Filename: piezometry_hubeau_07548X0009_F_20220101_20220331_D.csv
        # The regex captures greedily: id = "07548X0009_F"
        parts = parse_chronicle_filename("piezometry_hubeau_07548X0009_F_20220101_20220331_D.csv")
        assert parts is not None
        assert parts["type"] == "piezometry"
        assert parts["id"] == "07548X0009_F"

    def test_parse_loc(self):
        parts = parse_loc_filename("hydrometry_custom_LOC.csv")
        assert parts["type"] == "hydrometry"
        assert parts["source"] == "custom"
        assert parts["ext"] == "csv"

    def test_parse_loc_shp(self):
        parts = parse_loc_filename("piezometry_custom_LOC.shp")
        assert parts["ext"] == "shp"

    def test_invalid_returns_none(self):
        assert parse_chronicle_filename("random_file.csv") is None
        assert parse_loc_filename("random_file.csv") is None

    def test_safe_file_token(self):
        assert safe_file_token("07548X0009/F") == "07548X0009_F"
        assert safe_file_token("simple") == "simple"


class TestReadLocationsCSV:
    def test_standard_columns(self, tmp_path):
        csv_path = tmp_path / "loc.csv"
        pd.DataFrame({
            "id": ["A", "B"],
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "crs": ["EPSG:4326", "EPSG:4326"],
        }).to_csv(csv_path, index=False)

        locs = read_locations_csv(csv_path)
        assert len(locs) == 2
        assert locs[0].id == "A"
        assert locs[0].x == 1.0
        assert locs[0].crs == "EPSG:4326"

    def test_custom_columns(self, tmp_path):
        csv_path = tmp_path / "loc.csv"
        pd.DataFrame({
            "code": ["X1"],
            "lon": [10.0],
            "lat": [20.0],
        }).to_csv(csv_path, index=False)

        locs = read_locations_csv(
            csv_path, col_id="code", col_x="lon", col_y="lat", default_crs="EPSG:2154"
        )
        assert locs[0].id == "X1"
        assert locs[0].crs == "EPSG:2154"

    def test_missing_id_raises(self, tmp_path):
        csv_path = tmp_path / "loc.csv"
        pd.DataFrame({"x": [1], "y": [2]}).to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="missing id column"):
            read_locations_csv(csv_path)


class TestReadTimeseriesCSV:
    def test_standard(self, tmp_path):
        csv_path = tmp_path / "ts.csv"
        pd.DataFrame({
            "datetime": ["2020-01-01", "2020-01-02"],
            "value": [1.5, 2.5],
        }).to_csv(csv_path, index=False)

        df = read_timeseries_csv(csv_path)
        assert len(df) == 2
        assert "datetime" in df.columns
        assert "value" in df.columns

    def test_custom_columns(self, tmp_path):
        csv_path = tmp_path / "ts.csv"
        pd.DataFrame({
            "date": ["2020-01-01"],
            "debit": [3.14],
        }).to_csv(csv_path, index=False)

        df = read_timeseries_csv(csv_path, col_datetime="date", col_value="debit")
        assert df["value"].iloc[0] == pytest.approx(3.14)

    def test_missing_datetime_raises(self, tmp_path):
        csv_path = tmp_path / "ts.csv"
        pd.DataFrame({"value": [1]}).to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="missing datetime column"):
            read_timeseries_csv(csv_path)
