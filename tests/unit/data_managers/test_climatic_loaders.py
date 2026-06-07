"""Tests for custom grid loaders (load_custom_nc/tif, coord/time-dim detection)."""

from __future__ import annotations

import builtins
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.common.custom_grid_loader import (
    _find_coord,
    _find_time_dim,
    load_custom_nc,
)
from hydromodpy.data.contracts.spatial_field import FieldRecord


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
        ds["recharge"].attrs["nodata"] = -9999.0
        ds.attrs["crs"] = "EPSG:4326"
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
        ds["etp"].attrs["nodata"] = -9999.0
        ds.attrs["crs"] = "EPSG:4326"
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
        ds["etp"].attrs["nodata"] = -9999.0
        ds.attrs["crs"] = "EPSG:4326"
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
        ds["soil_k"].attrs["nodata"] = -9999.0
        ds.attrs["crs"] = "EPSG:4326"
        nc_path = tmp_path / "soil.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(nc_path, variable="soil_k", unit="m/s")
        rec = records[0]
        assert rec.date_start is None
        assert rec.date_end is None
        assert rec.frequency is None

    def test_load_rejects_missing_crs(self, tmp_path):
        ds = xr.Dataset(
            {"soil_k": (["x", "y"], np.ones((2, 2)))},
            coords={"x": [0.0, 1.0], "y": [0.0, 1.0]},
        )
        ds["soil_k"].attrs["nodata"] = -9999.0
        nc_path = tmp_path / "missing_crs.nc"
        ds.to_netcdf(nc_path)

        with pytest.raises(ValueError, match="CRS"):
            load_custom_nc(nc_path, variable="soil_k", unit="m/s")

    def test_load_uses_explicit_grid_metadata_fallbacks(self, tmp_path):
        times = pd.date_range("2020-01-01", periods=3, freq="D")
        ds = xr.Dataset(
            {"etp": (["time", "y", "x"], np.ones((3, 2, 2)))},
            coords={
                "time": times,
                "y": [6_813_000.0, 6_821_000.0],
                "x": [383_000.0, 391_000.0],
            },
        )
        nc_path = tmp_path / "etp_missing_metadata.nc"
        ds.to_netcdf(nc_path)

        records = load_custom_nc(
            nc_path,
            variable="etp",
            unit="mm/day",
            crs="EPSG:2154",
            nodata=-9999.0,
        )

        rec = records[0]
        assert rec.crs == "EPSG:2154"
        assert rec.bbox == (383_000.0, 6_813_000.0, 391_000.0, 6_821_000.0)
        assert rec.data["etp"].attrs["nodata"] == -9999.0

    def test_load_rejects_missing_nodata(self, tmp_path):
        ds = xr.Dataset(
            {"soil_k": (["x", "y"], np.ones((2, 2)))},
            coords={"x": [0.0, 1.0], "y": [0.0, 1.0]},
            attrs={"crs": "EPSG:4326"},
        )
        nc_path = tmp_path / "missing_nodata.nc"
        ds.to_netcdf(nc_path)

        with pytest.raises(ValueError, match="nodata"):
            load_custom_nc(nc_path, variable="soil_k", unit="m/s")


@pytest.mark.fast
class TestLoadCustomTif:
    def test_raises_import_error_when_rioxarray_not_available(self, monkeypatch):
        """If rioxarray is not installed, load_custom_tif should raise ImportError."""
        real_import = builtins.__import__

        def block_rioxarray_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "rioxarray":
                raise ImportError("rioxarray import blocked by test")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", block_rioxarray_import)

        from hydromodpy.data.common.custom_grid_loader import load_custom_tif

        with pytest.raises(ImportError, match="rioxarray import blocked by test"):
            load_custom_tif(Path("/fake.tif"), variable="x", unit="y")


@pytest.mark.fast
class TestFindTimeDim:
    @pytest.mark.parametrize(
        ("dims", "expected"),
        [
            (["time", "x"], "time"),
            (["t", "x"], "t"),
            (["datetime", "x"], "datetime"),
            (["date", "x"], "date"),
            (["TIME", "x"], "TIME"),
            (["x", "y"], None),
        ],
        ids=[
            "test_finds_time",
            "test_finds_t",
            "test_finds_datetime",
            "test_finds_date",
            "test_finds_TIME_uppercase",
            "test_returns_none_no_time",
        ],
    )
    def test_named_time_dim(self, dims, expected):
        ds = xr.Dataset({"v": (dims, np.zeros((3, 2)))})
        assert _find_time_dim(ds) == expected

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
    @pytest.mark.parametrize(
        ("coords", "candidates", "expected"),
        [
            ({"x": [1, 2], "y": [3, 4]}, ("x", "lon", "longitude"), "x"),
            ({"lon": [1, 2], "lat": [3, 4]}, ("x", "lon", "longitude"), "lon"),
            (
                {"LAMBX": [1, 2], "LAMBY": [3, 4]},
                ("x", "lon", "longitude", "LAMBX", "X"),
                "LAMBX",
            ),
            (
                {"Longitude": [1, 2], "Latitude": [3, 4]},
                ("x", "lon", "longitude"),
                "Longitude",
            ),
            ({"a": [1], "b": [2]}, ("x", "lon", "longitude"), None),
            ({"x": [1], "y": [2]}, ("y", "lat", "latitude", "LAMBY", "Y"), "y"),
        ],
        ids=[
            "test_finds_x",
            "test_finds_lon",
            "test_case_insensitive",
            "test_case_insensitive_lower_match",
            "test_returns_none_no_match",
            "test_finds_y",
        ],
    )
    def test_find_coord(self, coords, candidates, expected):
        ds = xr.Dataset(coords=coords)
        assert _find_coord(ds, candidates) == expected
