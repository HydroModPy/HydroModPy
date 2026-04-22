"""Tests for climatic variable data managers infrastructure.

Covers LoadResult, BaseFieldManager helpers, DataCatalog subsumption,
RechargeSourceConfig validation, and custom grid loaders.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.base_manager import BaseFieldManager
from hydromodpy.data.common.geo_helpers import bbox_hash as _bbox_hash
from hydromodpy.data.common.custom_grid_loader import (
    _find_coord,
    _find_time_dim,
    load_custom_nc,
)
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog


# ── helpers ──────────────────────────────────────────────────────────


def _make_point_record(station_id: str = "ST01", n: int = 5) -> PointRecord:
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
            "value": range(n),
        }
    )
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="custom",
        unit="mm/d",
        frequency="D",
        data=df,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, n),
    )


def _make_field_record(variable: str = "recharge") -> FieldRecord:
    ds = xr.Dataset({"data": (["x", "y"], np.zeros((3, 3)))})
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/d",
        source_unit="m/day",
        data=ds,
        bbox=(100.0, 200.0, 300.0, 400.0),
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
    )


# =====================================================================
# 1. LoadResult
# =====================================================================


@pytest.mark.fast
class TestLoadResultEmpty:
    def test_len_zero(self):
        r = LoadResult()
        assert len(r) == 0

    def test_bool_false(self):
        r = LoadResult()
        assert not r

    def test_has_points_false(self):
        r = LoadResult()
        assert r.has_points is False

    def test_has_fields_false(self):
        r = LoadResult()
        assert r.has_fields is False

    def test_all_records_empty(self):
        r = LoadResult()
        assert r.all_records == []


@pytest.mark.fast
class TestLoadResultPointsOnly:
    def test_has_points_true(self):
        r = LoadResult(points=[_make_point_record()])
        assert r.has_points is True

    def test_has_fields_false(self):
        r = LoadResult(points=[_make_point_record()])
        assert r.has_fields is False

    def test_len(self):
        r = LoadResult(points=[_make_point_record(), _make_point_record("ST02")])
        assert len(r) == 2

    def test_bool_true(self):
        r = LoadResult(points=[_make_point_record()])
        assert r


@pytest.mark.fast
class TestLoadResultFieldsOnly:
    def test_has_points_false(self):
        r = LoadResult(fields=[_make_field_record()])
        assert r.has_points is False

    def test_has_fields_true(self):
        r = LoadResult(fields=[_make_field_record()])
        assert r.has_fields is True

    def test_len(self):
        r = LoadResult(fields=[_make_field_record()])
        assert len(r) == 1


@pytest.mark.fast
class TestLoadResultMixed:
    def test_both_true(self):
        r = LoadResult(
            points=[_make_point_record()],
            fields=[_make_field_record()],
        )
        assert r.has_points is True
        assert r.has_fields is True

    def test_len_sums_both(self):
        r = LoadResult(
            points=[_make_point_record(), _make_point_record("ST02")],
            fields=[_make_field_record()],
        )
        assert len(r) == 3

    def test_all_records_flat_list(self):
        pt = _make_point_record()
        fr = _make_field_record()
        r = LoadResult(points=[pt], fields=[fr])
        flat = r.all_records
        assert len(flat) == 2
        assert flat[0] is pt
        assert flat[1] is fr


# =====================================================================
# 2. BaseFieldManager helpers
# =====================================================================


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


# =====================================================================
# 3. Catalog subsumption
# =====================================================================


@pytest.fixture
def catalog():
    """In-memory catalog for testing."""
    return DataCatalog(None)


def _register_grid(
    catalog,
    tmp_path,
    *,
    variable="recharge",
    source="sim2",
    bbox=(100, 200, 300, 400),
    date_start="2020-01-01",
    date_end="2020-12-31",
    is_custom=False,
    filename="grid.nc",
):
    """Helper: register a grid entry with a real file on disk."""
    f = tmp_path / filename
    f.write_text("dummy")
    return catalog.register(
        variable=variable,
        source=source,
        file_path=f,
        bbox=bbox,
        date_start=date_start,
        date_end=date_end,
        is_custom=is_custom,
    )


@pytest.mark.fast
class TestSubsumeEntries:
    def test_smaller_bbox_inside_larger_is_subsumed(self, catalog, tmp_path):
        """Smaller bbox+dates fully inside larger bbox+dates -> deleted."""
        small_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(150, 250, 250, 350),
            date_start="2020-03-01",
            date_end="2020-09-30",
            filename="small.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 1
        # Only the large entry remains
        df = catalog.list_entries()
        assert len(df) == 1
        assert df.iloc[0]["id"] == large_id

    def test_entry_outside_bbox_not_subsumed(self, catalog, tmp_path):
        """Entry with bbox outside the new larger bbox -> kept."""
        outside_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(500, 600, 700, 800),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="outside.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 2

    def test_custom_entries_never_subsumed(self, catalog, tmp_path):
        """Entries with is_custom=1 are never deleted by subsume."""
        custom_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(150, 250, 250, 350),
            date_start="2020-03-01",
            date_end="2020-09-30",
            is_custom=True,
            filename="custom.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 2

    def test_exclude_id_prevents_self_deletion(self, catalog, tmp_path):
        """The newly registered entry (exclude_id) is never subsumed."""
        entry_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="self.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=entry_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 1

    def test_upsert_different_files_no_collision(self, catalog, tmp_path):
        """Two grid files with station_id=NULL and different file_paths
        should coexist (not overwrite each other)."""
        f1 = tmp_path / "grid_a.nc"
        f1.write_text("a")
        f2 = tmp_path / "grid_b.nc"
        f2.write_text("b")

        id1 = catalog.register(
            variable="recharge",
            source="sim2",
            file_path=f1,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-06-30",
        )
        id2 = catalog.register(
            variable="recharge",
            source="sim2",
            file_path=f2,
            bbox=(100, 200, 300, 400),
            date_start="2020-07-01",
            date_end="2020-12-31",
        )
        assert id1 != id2
        assert len(catalog.list_entries()) == 2


# =====================================================================
# 4. Config validation (recharge as representative variable)
# =====================================================================


@pytest.mark.fast
class TestRechargeSourceConfigValidation:
    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            RechargeSourceConfig(source="custom")

    def test_custom_with_path_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_custom_with_source_unit_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path, source_unit="m/day")
        assert cfg.source_unit == "m/day"

    def test_sim2_without_path_ok(self):
        cfg = RechargeSourceConfig(source="sim2")
        assert cfg.source == "sim2"
        assert cfg.path is None

    def test_synthetic_requires_values(self):
        with pytest.raises(ValueError, match="values"):
            RechargeSourceConfig(source="synthetic")

    def test_synthetic_with_values_ok(self):
        cfg = RechargeSourceConfig(source="synthetic", values=[1.5, 2.0])
        assert cfg.source == "synthetic"
        assert cfg.values == [1.5, 2.0]

    def test_invalid_source_rejected(self):
        with pytest.raises(Exception):
            RechargeSourceConfig(source="unknown_provider")

    def test_literal_sources(self):
        """The allowed sources are exactly custom, sim2, synthetic."""
        # Verify each valid source is accepted (sim2 needs no extras,
        # custom needs path, synthetic needs values).
        RechargeSourceConfig(source="sim2")
        RechargeSourceConfig(source="custom", path=Path("/tmp"))
        RechargeSourceConfig(source="synthetic", values=[1.0])

        # Anything else is rejected
        for bad in ("nasa", "ERA5", ""):
            with pytest.raises(Exception):
                RechargeSourceConfig(source=bad)


# =====================================================================
# 5. Custom grid loader
# =====================================================================


@pytest.mark.fast
class TestLoadCustomNc:
    def test_load_roundtrip(self, tmp_path):
        """Save a simple xr.Dataset as .nc, load via load_custom_nc,
        verify FieldRecord contents."""
        times = pd.date_range("2020-01-01", periods=10, freq="D")
        raw_values = np.full((10, 4, 5), 0.25, dtype=float)
        ds = xr.Dataset(
            {
                "recharge": (["time", "x", "y"], raw_values),
            },
            coords={
                "time": times,
                "x": np.arange(4),
                "y": np.arange(5),
            },
        )
        ds["recharge"].attrs["units"] = "m/day"
        nc_path = tmp_path / "test_recharge.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(
            nc_path,
            variable="recharge",
            unit="mm/day",
        )

        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, FieldRecord)
        assert rec.variable == "recharge"
        assert rec.source == "custom"
        assert rec.unit == "mm/day"
        assert rec.source_unit == "m/day"
        assert rec.date_start is not None
        assert rec.date_end is not None
        assert rec.frequency == "D"
        assert np.allclose(rec.data["recharge"].values, raw_values * 1000.0)
        assert rec.data["recharge"].attrs["units"] == "mm/day"
        assert rec.data["recharge"].attrs["source_unit"] == "m/day"
        # bbox should reflect x/y coords
        assert rec.bbox[0] <= rec.bbox[2]  # xmin <= xmax
        assert rec.bbox[1] <= rec.bbox[3]  # ymin <= ymax

    def test_load_uses_explicit_source_unit_when_attrs_missing(self, tmp_path):
        times = pd.date_range("2020-01-01", periods=3, freq="D")
        raw_values = np.full((3, 2, 2), 0.5, dtype=float)
        ds = xr.Dataset(
            {
                "etp": (["time", "x", "y"], raw_values),
            },
            coords={
                "time": times,
                "x": [1.0, 2.0],
                "y": [10.0, 20.0],
            },
        )
        nc_path = tmp_path / "etp_explicit_source_unit.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(
            nc_path,
            variable="etp",
            unit="mm/day",
            source_unit="m/day",
        )

        rec = records[0]
        assert rec.unit == "mm/day"
        assert rec.source_unit == "m/day"
        assert np.allclose(rec.data["etp"].values, raw_values * 1000.0)
        assert rec.data["etp"].attrs["units"] == "mm/day"
        assert rec.data["etp"].attrs["source_unit"] == "m/day"

    def test_load_with_project_period_clips(self, tmp_path):
        """When project_period is given, temporal dimension is clipped."""
        times = pd.date_range("2020-01-01", periods=30, freq="D")
        ds = xr.Dataset(
            {
                "etp": (["time", "x", "y"], np.ones((30, 3, 3))),
            },
            coords={
                "time": times,
                "x": [1.0, 2.0, 3.0],
                "y": [10.0, 20.0, 30.0],
            },
        )
        nc_path = tmp_path / "etp.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(
            nc_path,
            variable="etp",
            unit="mm/d",
            project_period=(datetime(2020, 1, 10), datetime(2020, 1, 20)),
        )
        rec = records[0]
        # date range should be clipped to roughly 10th-20th
        assert rec.date_start >= datetime(2020, 1, 10)
        assert rec.date_end <= datetime(2020, 1, 20)

    def test_load_static_no_time(self, tmp_path):
        """Dataset without time dimension -> date_start/date_end are None."""
        ds = xr.Dataset(
            {
                "soil_k": (["x", "y"], np.ones((4, 5))),
            },
            coords={
                "x": np.arange(4),
                "y": np.arange(5),
            },
        )
        nc_path = tmp_path / "soil.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(nc_path, variable="soil_k", unit="m/s")
        rec = records[0]
        assert rec.date_start is None
        assert rec.date_end is None
        assert rec.frequency is None


@pytest.mark.fast
class TestLoadCustomTif:
    def test_skip_if_rioxarray_not_available(self):
        """If rioxarray is not installed, load_custom_tif should raise ImportError."""
        try:
            import rioxarray  # noqa: F401

            pytest.skip("rioxarray is available; skip-test not applicable")
        except ImportError:
            from hydromodpy.data.common.custom_grid_loader import (
                load_custom_tif,
            )

            with pytest.raises(ImportError):
                load_custom_tif(Path("/fake.tif"), variable="x", unit="y")


@pytest.mark.fast
class TestFindTimeDim:
    def test_finds_time(self):
        ds = xr.Dataset({"v": (["time", "x"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) == "time"

    def test_finds_t(self):
        ds = xr.Dataset({"v": (["t", "x"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) == "t"

    def test_finds_datetime(self):
        ds = xr.Dataset({"v": (["datetime", "x"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) == "datetime"

    def test_finds_date(self):
        ds = xr.Dataset({"v": (["date", "x"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) == "date"

    def test_finds_TIME_uppercase(self):
        ds = xr.Dataset({"v": (["TIME", "x"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) == "TIME"

    def test_returns_none_no_time(self):
        ds = xr.Dataset({"v": (["x", "y"], np.zeros((3, 2)))})
        assert _find_time_dim(ds) is None

    def test_detects_datetime64_dtype(self):
        """Dimension not named 'time' but with datetime64 dtype is detected."""
        times = pd.date_range("2020-01-01", periods=5, freq="D")
        ds = xr.Dataset(
            {"v": (["steps", "x"], np.zeros((5, 2)))},
            coords={"steps": times},
        )
        assert _find_time_dim(ds) == "steps"


@pytest.mark.fast
class TestFindCoord:
    def test_finds_x(self):
        ds = xr.Dataset(coords={"x": [1, 2], "y": [3, 4]})
        assert _find_coord(ds, ("x", "lon", "longitude")) == "x"

    def test_finds_lon(self):
        ds = xr.Dataset(coords={"lon": [1, 2], "lat": [3, 4]})
        assert _find_coord(ds, ("x", "lon", "longitude")) == "lon"

    def test_case_insensitive(self):
        ds = xr.Dataset(coords={"LAMBX": [1, 2], "LAMBY": [3, 4]})
        assert _find_coord(ds, ("x", "lon", "longitude", "LAMBX", "X")) == "LAMBX"

    def test_case_insensitive_lower_match(self):
        ds = xr.Dataset(coords={"Longitude": [1, 2], "Latitude": [3, 4]})
        assert _find_coord(ds, ("x", "lon", "longitude")) == "Longitude"

    def test_returns_none_no_match(self):
        ds = xr.Dataset(coords={"a": [1], "b": [2]})
        assert _find_coord(ds, ("x", "lon", "longitude")) is None

    def test_finds_y(self):
        ds = xr.Dataset(coords={"x": [1], "y": [2]})
        assert _find_coord(ds, ("y", "lat", "latitude", "LAMBY", "Y")) == "y"


# =====================================================================
# Recharge bridge tests
# =====================================================================


@pytest.mark.fast
class TestRechargeBridge:
    """Tests for the forcing bridge (LoadResult → flow-ready series)."""

    def test_extract_single_station(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        rec = _make_point_record("A", n=5)
        result = LoadResult(points=[rec])
        series = extract_homogeneous_series(result)
        assert series is not None
        assert len(series) == 5
        assert series.iloc[0] == 0.0
        assert series.iloc[4] == 4.0

    def test_extract_multiple_stations_averages(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        rec1 = PointRecord(
            station_id="A",
            variable="recharge",
            source="custom",
            unit="mm/d",
            frequency="D",
            data=pd.DataFrame({"datetime": dates, "value": [10.0, 20.0, 30.0]}),
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
        )
        rec2 = PointRecord(
            station_id="B",
            variable="recharge",
            source="custom",
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

    def test_extract_no_points_returns_none(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        result = LoadResult(fields=[_make_field_record()])
        assert extract_homogeneous_series(result) is None

    def test_extract_empty_result_returns_none(self):
        from hydromodpy.physics.forcing.forcing_bridge import extract_homogeneous_series

        result = LoadResult()
        assert extract_homogeneous_series(result) is None

    def test_build_forcing_series_converts_units(self):
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s

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

    def test_build_forcing_series_no_points_returns_none(self):
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s

        result = LoadResult(fields=[_make_field_record()])
        assert (
            build_forcing_series(
                result,
                unit_conversion_factor=factor_to_m_per_s("mm/day"),
                label="recharge",
            )
            is None
        )

    def test_build_forcing_series_runoff_converts_units(self):
        from hydromodpy.physics.forcing.forcing_bridge import build_forcing_series
        from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s

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
