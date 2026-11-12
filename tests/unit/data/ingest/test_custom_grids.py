"""Custom grids read from a user NetCDF or GeoTIFF: one FieldRecord per variable.

Values are converted to the internal unit (recharge in mm/day), nodata pixels become NaN,
and the box is (xmin, ymin, xmax, ymax) in the file CRS. The time and coordinate names
are found among the usual spellings.
"""

from __future__ import annotations

import builtins
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.ingest.custom_grids import (
    _find_coord,
    _find_time_dim,
    load_custom_nc,
    load_custom_tif,
)

TIMES = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]")
LAMBERT = {"y": [6790000.0, 6789975.0], "x": [350000.0, 350025.0]}


def lambert_grid(path: Path, *, fill_value: float | None) -> Path:
    """Three days of 2x2 recharge in m/day, the first pixel at -999."""
    data = np.full((3, 2, 2), 1.5, dtype="float32")
    data[0, 0, 0] = -999.0
    ds = xr.Dataset(
        {"recharge": (("time", "y", "x"), data, {"units": "mm/day"})},
        coords={"time": TIMES, **LAMBERT},
        attrs={"crs": "EPSG:2154"},
    )
    # None writes no fill value at all: the NetCDF writer adds NaN by default.
    ds.to_netcdf(path, encoding={"recharge": {"_FillValue": fill_value}})
    return path


def tif_with_nodata(path: Path) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    data = np.full((2, 2), 1.5, dtype="float32")
    data[0, 0] = -9999.0
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(350000.0, 6790000.0, 25.0, 25.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    return path


def nc_with_nodata_attribute(path: Path) -> Path:
    data = np.full((3, 2, 2), 1.5, dtype="float32")
    data[:, 0, 0] = -9999.0
    attrs = {"units": "mm/day", "nodata": -9999.0}
    xr.Dataset(
        {"recharge": (("time", "y", "x"), data, attrs)},
        coords={"time": TIMES, **LAMBERT},
        attrs={"crs": "EPSG:2154"},
    ).to_netcdf(path)
    return path


def static_soil_k(path: Path, *, nodata: float | None = None, crs: str | None = None) -> Path:
    """A 2x2 soil_k grid with no time axis, declaring the nodata value and CRS it is given."""
    ds = xr.Dataset(
        {"soil_k": (["x", "y"], np.ones((2, 2)))},
        coords={"x": [0.0, 1.0], "y": [0.0, 1.0]},
    )
    if nodata is not None:
        ds["soil_k"].attrs["nodata"] = nodata
    if crs is not None:
        ds.attrs["crs"] = crs
    ds.to_netcdf(path)
    return path


@pytest.mark.fast
def test_load_roundtrip(tmp_path):
    times = pd.date_range("2020-01-01", periods=10, freq="D")
    raw_values = np.full((10, 4, 5), 0.25, dtype=float)  # m/day
    ds = xr.Dataset(
        {"recharge": (["time", "x", "y"], raw_values)},
        coords={"time": times, "x": np.arange(4), "y": np.arange(5)},
    )
    ds["recharge"].attrs["units"] = "m/day"
    ds["recharge"].attrs["nodata"] = -9999.0
    ds.attrs["crs"] = "EPSG:4326"
    nc_path = tmp_path / "test_recharge.nc"
    ds.to_netcdf(nc_path)

    (rec,) = load_custom_nc(nc_path, variable="recharge", unit="mm/day")

    assert isinstance(rec, FieldRecord)
    assert rec.variable == "recharge"
    assert rec.source == "file"
    assert rec.unit == "mm/day"
    assert rec.source_unit == "m/day"
    assert rec.date_start is not None
    assert rec.date_end is not None
    assert rec.frequency == "D"
    np.testing.assert_allclose(rec.data["recharge"].values, raw_values * 1000.0)  # m to mm
    assert rec.data["recharge"].attrs["units"] == "mm/day"
    assert rec.data["recharge"].attrs["source_unit"] == "m/day"
    assert rec.bbox[0] <= rec.bbox[2]
    assert rec.bbox[1] <= rec.bbox[3]


@pytest.mark.fast
def test_explicit_source_unit_when_attrs_are_missing(tmp_path):
    raw_values = np.full((3, 2, 2), 0.5, dtype=float)  # m/day
    ds = xr.Dataset(
        {"etp": (["time", "x", "y"], raw_values)},
        coords={
            "time": pd.date_range("2020-01-01", periods=3, freq="D"),
            "x": [1.0, 2.0],
            "y": [10.0, 20.0],
        },
    )
    ds["etp"].attrs["nodata"] = -9999.0
    ds.attrs["crs"] = "EPSG:4326"
    nc_path = tmp_path / "etp_explicit_source_unit.nc"
    ds.to_netcdf(nc_path)

    (rec,) = load_custom_nc(nc_path, variable="etp", unit="mm/day", source_unit="m/day")

    assert rec.unit == "mm/day"
    assert rec.source_unit == "m/day"
    np.testing.assert_allclose(rec.data["etp"].values, raw_values * 1000.0)
    assert rec.data["etp"].attrs["units"] == "mm/day"
    assert rec.data["etp"].attrs["source_unit"] == "m/day"


@pytest.mark.fast
def test_static_grid_has_no_dates(tmp_path):
    path = static_soil_k(tmp_path / "soil.nc", nodata=-9999.0, crs="EPSG:4326")

    (rec,) = load_custom_nc(path, variable="soil_k", unit="m/s")

    assert rec.date_start is None
    assert rec.date_end is None
    assert rec.frequency is None


@pytest.mark.fast
def test_crs_and_nodata_given_by_the_caller(tmp_path):
    ds = xr.Dataset(
        {"etp": (["time", "y", "x"], np.ones((3, 2, 2)))},
        coords={
            "time": pd.date_range("2020-01-01", periods=3, freq="D"),
            "y": [6_813_000.0, 6_821_000.0],
            "x": [383_000.0, 391_000.0],
        },
    )
    nc_path = tmp_path / "etp_missing_metadata.nc"
    ds.to_netcdf(nc_path)

    (rec,) = load_custom_nc(nc_path, variable="etp", unit="mm/day", crs="EPSG:2154", nodata=-9999.0)

    assert rec.crs == "EPSG:2154"
    assert rec.bbox == (383_000.0, 6_813_000.0, 391_000.0, 6_821_000.0)
    assert rec.data["etp"].attrs["nodata"] == -9999.0


@pytest.mark.fast
def test_the_fill_value_is_read_as_nodata(tmp_path):
    # xarray moves _FillValue to the encoding when it opens the file.
    path = lambert_grid(tmp_path / "recharge.nc", fill_value=-999.0)

    (record,) = load_custom_nc(
        path,
        variable="recharge",
        unit="mm/day",
        project_period=(datetime(2020, 1, 1), datetime(2020, 1, 3)),
    )

    assert float(record.data["recharge"].attrs["nodata"]) == -999.0
    assert np.isnan(float(record.data["recharge"].isel(time=0, y=0, x=0)))


@pytest.mark.fast
@pytest.mark.parametrize(
    ("name", "write", "loader", "kwargs"),
    [
        pytest.param(
            "recharge.tif",
            tif_with_nodata,
            load_custom_tif,
            {"unit": "m/day", "source_unit": "mm/day"},
            id="geotiff",
        ),
        pytest.param(
            "recharge.nc",
            nc_with_nodata_attribute,
            load_custom_nc,
            {"unit": "m/day"},
            id="netcdf nodata attribute",
        ),
    ],
)
def test_a_nodata_pixel_stays_masked_through_a_unit_conversion(
    tmp_path: Path, name, write, loader, kwargs
) -> None:
    (record,) = loader(write(tmp_path / name), variable="recharge", **kwargs)

    values = record.data["recharge"].values.reshape(-1, 4)[0]
    assert np.isnan(values[0]) or values[0] == float(record.data["recharge"].attrs["nodata"])
    assert values[1] == pytest.approx(1.5e-3)  # 1.5 mm/day in m/day


@pytest.mark.fast
def test_tif_loader_needs_rioxarray(monkeypatch):
    real_import = builtins.__import__

    def block_rioxarray_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "rioxarray":
            raise ImportError("rioxarray import blocked by test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_rioxarray_import)

    with pytest.raises(ImportError, match="rioxarray import blocked by test"):
        load_custom_tif(Path("/fake.tif"), variable="x", unit="y")


@pytest.mark.fast
@pytest.mark.parametrize(
    ("dims", "expected"),
    [
        pytest.param(["time", "x"], "time", id="time"),
        pytest.param(["t", "x"], "t", id="t"),
        pytest.param(["datetime", "x"], "datetime", id="datetime"),
        pytest.param(["date", "x"], "date", id="date"),
        pytest.param(["TIME", "x"], "TIME", id="upper case"),
        pytest.param(["x", "y"], None, id="no time"),
    ],
)
def test_time_dim_by_name(dims, expected):
    ds = xr.Dataset({"v": (dims, np.zeros((3, 2)))})

    assert _find_time_dim(ds) == expected


@pytest.mark.fast
def test_time_dim_by_dtype():
    ds = xr.Dataset(
        {"v": (["steps", "x"], np.zeros((5, 2)))},
        coords={"steps": pd.date_range("2020-01-01", periods=5, freq="D")},
    )

    assert _find_time_dim(ds) == "steps"


X_NAMES = ("x", "lon", "longitude")
Y_NAMES = ("y", "lat", "latitude", "LAMBY", "Y")


@pytest.mark.fast
@pytest.mark.parametrize(
    ("coords", "candidates", "expected"),
    [
        pytest.param({"x": [1, 2], "y": [3, 4]}, X_NAMES, "x", id="x"),
        pytest.param({"lon": [1, 2], "lat": [3, 4]}, X_NAMES, "lon", id="lon"),
        pytest.param(
            {"LAMBX": [1, 2], "LAMBY": [3, 4]},
            ("x", "lon", "longitude", "LAMBX", "X"),
            "LAMBX",
            id="case insensitive",
        ),
        pytest.param(
            {"Longitude": [1, 2], "Latitude": [3, 4]}, X_NAMES, "Longitude", id="lower case match"
        ),
        pytest.param({"a": [1], "b": [2]}, X_NAMES, None, id="no match"),
        pytest.param({"x": [1], "y": [2]}, Y_NAMES, "y", id="y"),
    ],
)
def test_coord_by_name(coords, candidates, expected):
    assert _find_coord(xr.Dataset(coords=coords), candidates) == expected


def fill_value_none(path: Path) -> Path:
    return lambert_grid(path, fill_value=None)


def fill_value_minus_999(path: Path) -> Path:
    return lambert_grid(path, fill_value=-999.0)


def no_crs(path: Path) -> Path:
    return static_soil_k(path, nodata=-9999.0)


def no_nodata(path: Path) -> Path:
    return static_soil_k(path, crs="EPSG:4326")


REFUSALS = [
    pytest.param(
        fill_value_none, {"unit": "mm/day"}, "must declare a nodata value", id="no nodata at all"
    ),
    pytest.param(
        fill_value_minus_999,
        {
            "unit": "mm/day",
            "project_period": (datetime(2030, 1, 1), datetime(2030, 1, 2)),
        },
        "holds no date in the period",
        id="window outside the file",
    ),
    pytest.param(no_crs, {"variable": "soil_k", "unit": "m/s"}, "CRS", id="no crs"),
    pytest.param(no_nodata, {"variable": "soil_k", "unit": "m/s"}, "nodata", id="no nodata value"),
]


@pytest.mark.parametrize(("write", "kwargs", "said"), REFUSALS)
def test_refusals(tmp_path, write, kwargs, said):
    path = write(tmp_path / "grid.nc")

    with pytest.raises(ValueError, match=said):
        load_custom_nc(path, **{"variable": "recharge"} | kwargs)
