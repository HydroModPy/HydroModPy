"""The records that the data layer hands up: points, fields, load results, completeness."""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.completeness import compute_completeness
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from tests._helpers.data_climatic_builders import _make_field_record, _make_point_record


class TestStationLocation:
    def test_to_dict(self):
        loc = StationLocation(id="A", x=1.0, y=2.0, crs="EPSG:2154", metadata={"name": "Test"})
        d = loc.to_dict()
        assert d["id"] == "A"
        assert d["name"] == "Test"

    def test_numpy_metadata_writes_to_json(self):
        metadata = {"influence": np.int64(1), "active": np.bool_(True), "altitude": np.float64(1.5)}
        loc = StationLocation(id="A", x=1.0, y=2.0, crs="EPSG:2154", metadata=metadata)
        assert json.loads(json.dumps(loc.to_dict()))["influence"] == 1
        assert type(loc.metadata["influence"]) is int
        assert type(loc.metadata["active"]) is bool


class TestPointRecord:
    def _make_df(self, n=10):
        return pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
                "value": range(n),
            }
        )

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"date": ["2020-01-01"], "val": [1.0]})
        with pytest.raises(ValueError, match="missing columns"):
            PointRecord(
                station_id="S1",
                variable="x",
                source="x",
                unit="x",
                frequency="D",
                data=df,
                date_start=datetime(2020, 1, 1),
                date_end=datetime(2020, 1, 1),
            )

    def test_filter_by_period(self):
        df = self._make_df(30)
        rec = PointRecord(
            station_id="S1",
            variable="discharge",
            source="file",
            unit="m3/s",
            frequency="D",
            data=df,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 30),
            source_unit="L/s",
        )
        filtered = rec.filter_by_period(datetime(2020, 1, 5), datetime(2020, 1, 15))
        assert filtered.n_records == 11  # 5th to 15th inclusive
        assert filtered.source_unit == "L/s"

    def test_filter_recomputes_quality(self):
        df = self._make_df(30)
        rec = PointRecord(
            station_id="S1",
            variable="discharge",
            source="file",
            unit="m3/s",
            frequency="D",
            data=df,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 30),
        )
        filtered = rec.filter_by_period(datetime(2020, 1, 1), datetime(2020, 1, 10))
        assert filtered.quality["n_expected"] == 10
        assert filtered.quality["completeness_pct"] == 100.0


class TestLoadResult:
    def test_warnings(self):
        lr = LoadResult(warnings=["Station S2 missing data", "Timeout on API"])
        assert len(lr.warnings) == 2
        assert "Timeout" in lr.warnings[1]

    def test_warnings_default_independent(self):
        lr1 = LoadResult()
        lr1.warnings.append("oops")
        lr2 = LoadResult()
        assert lr2.warnings == []


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


@pytest.mark.fast
class TestLoadResultEmpty:
    def test_bool_false(self):
        r = LoadResult()
        assert not r

    def test_all_records_empty(self):
        r = LoadResult()
        assert r.all_records == []


@pytest.mark.fast
class TestLoadResultPointsOnly:
    def test_len(self):
        r = LoadResult(points=[_make_point_record(), _make_point_record("ST02")])
        assert len(r) == 2

    def test_bool_true(self):
        r = LoadResult(points=[_make_point_record()])
        assert r


@pytest.mark.fast
class TestLoadResultFieldsOnly:
    def test_len(self):
        r = LoadResult(fields=[_make_field_record()])
        assert len(r) == 1


@pytest.mark.fast
class TestLoadResultMixed:
    def test_all_records_flat_list(self):
        pt = _make_point_record()
        fr = _make_field_record()
        r = LoadResult(points=[pt], fields=[fr])
        flat = r.all_records
        assert len(flat) == 2
        assert flat[0] is pt
        assert flat[1] is fr


@pytest.mark.fast
class TestRechargeBridge:
    """Tests for the forcing bridge (LoadResult → flow-ready series)."""

    def test_extract_multiple_stations_averages(self):
        from hydromodpy.model.forcing.forcing_bridge import extract_homogeneous_series

        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        rec1 = PointRecord(
            station_id="A",
            variable="recharge",
            source="file",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": [10.0, 20.0, 30.0]}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )
        rec2 = PointRecord(
            station_id="B",
            variable="recharge",
            source="file",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": [20.0, 40.0, 60.0]}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )
        result = LoadResult(points=[rec1, rec2])
        series = extract_homogeneous_series(result)
        assert series is not None
        assert len(series) == 3
        assert series.iloc[0] == pytest.approx(15.0)
        assert series.iloc[1] == pytest.approx(30.0)

    def test_build_forcing_series_converts_units(self):
        from hydromodpy.core.units.quantities import factor_to_m_per_s
        from hydromodpy.model.forcing.forcing_bridge import build_forcing_series

        mm_day_to_m_s = factor_to_m_per_s("mm/day")
        rec = _make_point_record("A", n=3)
        result = LoadResult(points=[rec])
        series = build_forcing_series(
            result,
            unit_conversion_factor=mm_day_to_m_s,
            label="recharge",
        )
        assert series is not None
        # Value 1 (mm/day) → 1 * factor_to_m_per_s("mm/day") (m/s)
        assert series.iloc[1] == pytest.approx(1.0 * mm_day_to_m_s)

    def test_build_forcing_series_runoff_converts_units(self):
        from hydromodpy.core.units.quantities import factor_to_m_per_s
        from hydromodpy.model.forcing.forcing_bridge import build_forcing_series

        mm_day_to_m_s = factor_to_m_per_s("mm/day")
        rec = _make_point_record("A", n=3)
        result = LoadResult(points=[rec])
        series = build_forcing_series(
            result,
            unit_conversion_factor=mm_day_to_m_s,
            label="runoff",
        )
        assert series is not None
        assert series.iloc[2] == pytest.approx(2.0 * mm_day_to_m_s)
