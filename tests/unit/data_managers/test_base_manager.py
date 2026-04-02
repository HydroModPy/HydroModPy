"""Tests for BaseVariableManager cache merge utilities."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from hydromodpy.data.common.base_manager import BaseVariableManager
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog


class _DummyManager(BaseVariableManager):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"

    def _fetch_from_source(self, source_cfg):
        return []


def _make_record(station_id, start, end, values=None):
    dates = pd.date_range(start, end, freq="D")
    if values is None:
        values = range(len(dates))
    df = pd.DataFrame({"datetime": dates, "value": list(values)[:len(dates)]})
    return PointRecord(
        station_id=station_id, variable="discharge", source="hubeau",
        unit="m3/s", frequency="D", data=df,
        date_start=start, date_end=end,
        source_unit="L/s",
    )


class TestComputeMissingPeriods:

    def test_full_coverage(self):
        mgr = _DummyManager(
            config=None, catalog=DataCatalog(),
            project_period=(datetime(2020, 6, 1), datetime(2020, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1), datetime(2021, 12, 31),
        )
        assert gaps == []

    def test_gap_before(self):
        mgr = _DummyManager(
            config=None, catalog=DataCatalog(),
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 6, 1), datetime(2020, 12, 31),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2020, 1, 1)
        assert gaps[0][1] == datetime(2020, 5, 31)

    def test_gap_after(self):
        mgr = _DummyManager(
            config=None, catalog=DataCatalog(),
            project_period=(datetime(2020, 1, 1), datetime(2022, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1), datetime(2021, 6, 30),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2021, 7, 1)
        assert gaps[0][1] == datetime(2022, 12, 31)

    def test_gap_both_sides(self):
        mgr = _DummyManager(
            config=None, catalog=DataCatalog(),
            project_period=(datetime(2019, 1, 1), datetime(2023, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1), datetime(2022, 12, 31),
        )
        assert len(gaps) == 2

    def test_no_project_period(self):
        mgr = _DummyManager(config=None, catalog=DataCatalog())
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1), datetime(2020, 12, 31),
        )
        assert gaps == []


class TestMergeIntoRecord:

    def test_merge_deduplicates(self):
        mgr = _DummyManager(config=None, catalog=DataCatalog())
        r1 = _make_record("ST01", datetime(2020, 1, 1), datetime(2020, 1, 10))
        r2 = _make_record("ST01", datetime(2020, 1, 8), datetime(2020, 1, 15))

        merged = mgr._merge_into_record(r1, r2)

        assert merged.station_id == "ST01"
        assert merged.date_start == datetime(2020, 1, 1)
        assert merged.date_end == datetime(2020, 1, 15)
        # 15 unique days, no duplicates
        assert len(merged.data) == 15
        assert merged.data["datetime"].is_monotonic_increasing
        assert merged.source_unit == "L/s"

    def test_merge_no_overlap(self):
        mgr = _DummyManager(config=None, catalog=DataCatalog())
        r1 = _make_record("ST01", datetime(2020, 1, 1), datetime(2020, 1, 5))
        r2 = _make_record("ST01", datetime(2020, 1, 10), datetime(2020, 1, 15))

        merged = mgr._merge_into_record(r1, r2)

        assert len(merged.data) == 11  # 5 + 6
        assert merged.date_start == datetime(2020, 1, 1)
        assert merged.date_end == datetime(2020, 1, 15)
