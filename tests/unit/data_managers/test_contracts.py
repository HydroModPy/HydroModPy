"""Tests for contracts (PointRecord, StationLocation, FieldRecord)."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord


class TestStationLocation:
    def test_creation(self):
        loc = StationLocation(id="ST01", x=-1.5, y=48.1, crs="EPSG:4326")
        assert loc.id == "ST01"
        assert loc.x == -1.5
        assert loc.crs == "EPSG:4326"
        assert loc.metadata == {}

    def test_frozen(self):
        loc = StationLocation(id="ST01", x=0, y=0, crs="EPSG:4326")
        with pytest.raises(AttributeError):
            loc.id = "changed"

    def test_to_dict(self):
        loc = StationLocation(id="A", x=1.0, y=2.0, crs="EPSG:2154", metadata={"name": "Test"})
        d = loc.to_dict()
        assert d["id"] == "A"
        assert d["name"] == "Test"


class TestPointRecord:
    def _make_df(self, n=10):
        return pd.DataFrame({
            "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
            "value": range(n),
        })

    def test_creation(self):
        df = self._make_df()
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 10),
        )
        assert rec.n_records == 10
        assert rec.has_data

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"date": ["2020-01-01"], "val": [1.0]})
        with pytest.raises(ValueError, match="missing columns"):
            PointRecord(
                station_id="S1", variable="x", source="x",
                unit="x", frequency="D", data=df,
                date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 1),
            )

    def test_filter_by_period(self):
        df = self._make_df(30)
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 30),
            source_unit="L/s",
        )
        filtered = rec.filter_by_period(datetime(2020, 1, 5), datetime(2020, 1, 15))
        assert filtered.n_records == 11  # 5th to 15th inclusive
        assert filtered.source_unit == "L/s"
