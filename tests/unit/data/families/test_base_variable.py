"""The base classes of the station and grid variables."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.grids import GridVariable
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.provenance.sidecars import CacheIndex
from tests._helpers.data_climatic_builders import _make_field_record


class _DummyStations(StationVariable):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"

    def _fetch_from_source(self, source_cfg):
        return []


def _make_record(station_id, start, end, values=None):
    dates = pd.date_range(start, end, freq="D")
    if values is None:
        values = range(len(dates))
    df = pd.DataFrame({"datetime": dates, "value": list(values)[: len(dates)]})
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=df,
        date_start=start,
        date_end=end,
        source_unit="L/s",
    )


class TestComputeMissingPeriods:
    def test_gap_before(self):
        mgr = _DummyStations(
            config=None,
            index=CacheIndex(None),
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 6, 1),
            datetime(2020, 12, 31),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2020, 1, 1)
        assert gaps[0][1] == datetime(2020, 5, 31)

    def test_gap_both_sides(self):
        mgr = _DummyStations(
            config=None,
            index=CacheIndex(None),
            project_period=(datetime(2019, 1, 1), datetime(2023, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2022, 12, 31),
        )
        assert len(gaps) == 2

    def test_no_project_period(self):
        mgr = _DummyStations(config=None, index=CacheIndex(None))
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        assert gaps == []


class TestMergeIntoRecord:
    def test_merge_deduplicates(self):
        mgr = _DummyStations(config=None, index=CacheIndex(None))
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
        mgr = _DummyStations(config=None, index=CacheIndex(None))
        r1 = _make_record("ST01", datetime(2020, 1, 1), datetime(2020, 1, 5))
        r2 = _make_record("ST01", datetime(2020, 1, 10), datetime(2020, 1, 15))

        merged = mgr._merge_into_record(r1, r2)

        assert len(merged.data) == 11  # 5 + 6
        assert merged.date_start == datetime(2020, 1, 1)
        assert merged.date_end == datetime(2020, 1, 15)


class _DummyGrids(GridVariable):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/d"

    def _fetch_from_source(self, source_cfg):
        return []


@pytest.mark.fast
class TestNcFilename:
    def test_same_bbox_same_hash(self):
        bbox = (1.5, 2.5, 3.5, 4.5)
        n1 = GridVariable._nc_filename("etp", "sim2", bbox, None, None)
        n2 = GridVariable._nc_filename("etp", "sim2", bbox, None, None)
        assert n1 == n2

    def test_no_bbox_no_dates(self):
        name = GridVariable._nc_filename("recharge", "custom", None, None, None)
        assert name == "recharge_custom.nc"


@pytest.mark.fast
class TestHandleFileResults:
    def test_empty_list(self):
        mgr = _DummyGrids(config=None, index=None)
        source_cfg = MagicMock()
        source_cfg.mask_path = None
        result = mgr._handle_file_results([], source_cfg)
        assert result == []

    def test_a_user_file_is_no_row_of_the_cache(self):
        index = MagicMock()
        variable = _DummyGrids(config=None, index=index)
        fr = _make_field_record()
        source_cfg = MagicMock()
        source_cfg.mask_path = None
        result = variable._handle_file_results([fr], source_cfg)
        assert len(result) == 1
        assert isinstance(result[0], FieldRecord)
        # The file is read where it lies: nothing is written to the index.
        assert index.mock_calls == []
