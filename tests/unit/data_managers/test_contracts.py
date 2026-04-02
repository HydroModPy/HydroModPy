"""Tests for contracts (PointRecord, StationLocation, FieldRecord, LoadResult)."""

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord


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

    def test_quality_auto_computed(self):
        df = self._make_df(10)
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 10),
        )
        assert rec.quality is not None
        assert rec.quality["completeness_pct"] == 100.0
        assert rec.quality["n_expected"] == 10
        assert rec.quality["n_actual"] == 10
        assert rec.quality["n_missing"] == 0
        assert rec.quality["n_gaps"] == 0

    def test_quality_with_gaps(self):
        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-05",
                                "2020-01-09", "2020-01-10"])
        df = pd.DataFrame({"datetime": dates, "value": range(5)})
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 10),
        )
        assert rec.quality["completeness_pct"] == 50.0
        assert rec.quality["n_missing"] == 5
        assert rec.quality["n_gaps"] == 2

    def test_quality_not_overwritten_when_provided(self):
        df = self._make_df(5)
        custom_quality = {"completeness_pct": 42.0, "custom": True}
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 5),
            quality=custom_quality,
        )
        assert rec.quality["completeness_pct"] == 42.0
        assert rec.quality["custom"] is True

    def test_quality_none_on_empty_data(self):
        df = pd.DataFrame({"datetime": pd.Series(dtype="datetime64[ns]"),
                           "value": pd.Series(dtype="float64")})
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 10),
        )
        assert rec.quality is None

    def test_filter_recomputes_quality(self):
        df = self._make_df(30)
        rec = PointRecord(
            station_id="S1", variable="discharge", source="custom",
            unit="m3/s", frequency="D", data=df,
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 1, 30),
        )
        filtered = rec.filter_by_period(datetime(2020, 1, 1), datetime(2020, 1, 10))
        assert filtered.quality["n_expected"] == 10
        assert filtered.quality["completeness_pct"] == 100.0


class TestLoadResult:
    def test_empty(self):
        lr = LoadResult()
        assert len(lr) == 0
        assert not lr
        assert lr.warnings == []

    def test_warnings(self):
        lr = LoadResult(warnings=["Station S2 missing data", "Timeout on API"])
        assert len(lr.warnings) == 2
        assert "Timeout" in lr.warnings[1]

    def test_warnings_default_independent(self):
        lr1 = LoadResult()
        lr1.warnings.append("oops")
        lr2 = LoadResult()
        assert lr2.warnings == []
