"""The base managers of variables and fields."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from hydromodpy.data.common.geo_helpers import bbox_hash as _bbox_hash
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog
from tests._helpers.data_climatic_builders import _make_field_record, _make_point_record


class _DummyManager(BaseVariableManager):
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
    def test_full_coverage(self):
        mgr = _DummyManager(
            config=None,
            catalog=DataCatalog(),
            project_period=(datetime(2020, 6, 1), datetime(2020, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2021, 12, 31),
        )
        assert gaps == []

    def test_gap_before(self):
        mgr = _DummyManager(
            config=None,
            catalog=DataCatalog(),
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 6, 1),
            datetime(2020, 12, 31),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2020, 1, 1)
        assert gaps[0][1] == datetime(2020, 5, 31)

    def test_gap_after(self):
        mgr = _DummyManager(
            config=None,
            catalog=DataCatalog(),
            project_period=(datetime(2020, 1, 1), datetime(2022, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2021, 6, 30),
        )
        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2021, 7, 1)
        assert gaps[0][1] == datetime(2022, 12, 31)

    def test_gap_both_sides(self):
        mgr = _DummyManager(
            config=None,
            catalog=DataCatalog(),
            project_period=(datetime(2019, 1, 1), datetime(2023, 12, 31)),
        )
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2022, 12, 31),
        )
        assert len(gaps) == 2

    def test_no_project_period(self):
        mgr = _DummyManager(config=None, catalog=DataCatalog())
        gaps = mgr._compute_missing_periods(
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
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


class _DummyFieldManager(BaseFieldManager):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/d"

    def _fetch_from_source(self, source_cfg):
        return []


@pytest.mark.fast
class TestNcFilename:
    def test_deterministic_with_bbox(self):
        bbox = (100.0, 200.0, 300.0, 400.0)
        name = BaseFieldManager._nc_filename(
            "recharge",
            "sim2",
            bbox,
            datetime(2020, 1, 1),
            datetime(2020, 12, 31),
        )
        expected_hash = _bbox_hash(bbox)
        assert name == f"recharge_sim2_{expected_hash}_20200101_20201231.nc"

    def test_same_bbox_same_hash(self):
        bbox = (1.5, 2.5, 3.5, 4.5)
        n1 = BaseFieldManager._nc_filename("etp", "sim2", bbox, None, None)
        n2 = BaseFieldManager._nc_filename("etp", "sim2", bbox, None, None)
        assert n1 == n2

    def test_different_bbox_different_hash(self):
        n1 = BaseFieldManager._nc_filename(
            "etp",
            "sim2",
            (1.0, 2.0, 3.0, 4.0),
            None,
            None,
        )
        n2 = BaseFieldManager._nc_filename(
            "etp",
            "sim2",
            (10.0, 20.0, 30.0, 40.0),
            None,
            None,
        )
        assert n1 != n2

    def test_no_bbox_no_dates(self):
        name = BaseFieldManager._nc_filename("recharge", "custom", None, None, None)
        assert name == "recharge_custom.nc"

    def test_bbox_hash_is_md5_prefix(self):
        bbox = (1.0, 2.0, 3.0, 4.0)
        s = f"{bbox[0]:.6f}_{bbox[1]:.6f}_{bbox[2]:.6f}_{bbox[3]:.6f}"
        expected = hashlib.md5(s.encode()).hexdigest()[:8]
        assert _bbox_hash(bbox) == expected


@pytest.mark.fast
class TestHandleCustomResults:
    def test_separates_point_and_field_records(self):
        mgr = _DummyFieldManager(config=None, catalog=None)
        pt = _make_point_record()
        fr = _make_field_record()

        # source_cfg needs mask_path attribute for _apply_mask check
        source_cfg = MagicMock()
        source_cfg.mask_path = None

        result = mgr._handle_custom_results([pt, fr], source_cfg)

        # PointRecords pass through (no mask), FieldRecords appended
        point_results = [r for r in result if isinstance(r, PointRecord)]
        field_results = [r for r in result if isinstance(r, FieldRecord)]
        assert len(point_results) == 1
        assert len(field_results) == 1

    def test_empty_list(self):
        mgr = _DummyFieldManager(config=None, catalog=None)
        source_cfg = MagicMock()
        source_cfg.mask_path = None
        result = mgr._handle_custom_results([], source_cfg)
        assert result == []

    def test_points_only(self):
        mgr = _DummyFieldManager(config=None, catalog=None)
        pt = _make_point_record()
        source_cfg = MagicMock()
        source_cfg.mask_path = None
        result = mgr._handle_custom_results([pt], source_cfg)
        assert len(result) == 1
        assert isinstance(result[0], PointRecord)

    def test_fields_only_with_catalog(self):
        catalog = MagicMock()
        mgr = _DummyFieldManager(config=None, catalog=catalog)
        fr = _make_field_record()
        source_cfg = MagicMock()
        source_cfg.mask_path = None
        result = mgr._handle_custom_results([fr], source_cfg)
        assert len(result) == 1
        assert isinstance(result[0], FieldRecord)
        # _register_custom_fields should have been called internally
        catalog.register.assert_called_once()
        assert catalog.register.call_args.kwargs["source_unit"] == "m/day"
