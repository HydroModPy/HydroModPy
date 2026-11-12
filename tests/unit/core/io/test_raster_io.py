"""Raster helpers of ``core.io``: the masks, the GeoTIFF writers and the loaders.

Each helper is a capability a workflow may call, so each gets a round trip on a
tiny GeoTIFF in Lambert-93 (EPSG:2154): write it, read it back, same values and
same frame.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
import rioxarray  # noqa: F401 - registers the .rio accessor load_to_xarray relies on
import xarray as xr
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.core.io import raster_io

ORIGIN_X, ORIGIN_Y, CELL = 700_000.0, 6_600_000.0, 100.0
NODATA = -9999.0


def _profile(height: int = 4, width: int = 5, *, crs: str | None = "EPSG:2154") -> dict:
    return {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": from_origin(ORIGIN_X, ORIGIN_Y, CELL, CELL),
        "nodata": NODATA,
    }


def _dem(path: Path, *, crs: str | None = "EPSG:2154") -> np.ndarray:
    values = np.arange(20, dtype="float32").reshape(4, 5) + 100.0
    raster_io.write_band(path, values, _profile(crs=crs))
    return values


# ---- write_band ------------------------------------------------------------


# ---- export_tif ------------------------------------------------------------


def test_export_tif_nodata_is_the_one_given_and_else_the_one_of_the_reference(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.tif"
    _dem(base)
    data = np.zeros((4, 5), "float32")

    raster_io.export_tif(base, data, tmp_path / "same.tif")
    raster_io.export_tif(base, data, tmp_path / "other.tif", data_nodata_val=-1.0)

    with (
        rasterio.open(tmp_path / "same.tif") as same,
        rasterio.open(tmp_path / "other.tif") as other,
    ):
        assert same.nodata == NODATA
        assert other.nodata == -1.0


@pytest.mark.parametrize("crs_like", ["EPSG:27572", 27572, CRS.from_epsg(27572)])
def test_export_tif_stamps_the_crs_whatever_way_it_is_named(tmp_path: Path, crs_like) -> None:
    base = tmp_path / "base.tif"
    _dem(base)

    raster_io.export_tif(base, np.zeros((4, 5), "float32"), tmp_path / "out.tif", data_crs=crs_like)

    with rasterio.open(tmp_path / "out.tif") as out:
        assert out.crs.to_epsg() == 27572


# ---- load_to_numpy ---------------------------------------------------------


def test_a_raster_on_a_finer_grid_is_resampled_onto_the_reference_grid(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    fine = _profile(8, 10)
    fine["transform"] = from_origin(ORIGIN_X, ORIGIN_Y, CELL / 2, CELL / 2)
    raster_io.write_band(tmp_path / "fine.tif", np.full((8, 10), 7.0, "float32"), fine)

    values, *_ = raster_io.load_to_numpy(
        tmp_path / "fine.tif", base_path=str(tmp_path / "base.tif")
    )

    assert values.shape == (4, 5)
    np.testing.assert_allclose(values, 7.0)


def test_a_raster_with_a_missing_crs_takes_the_one_declared_by_the_caller(tmp_path: Path) -> None:
    _dem(tmp_path / "nocrs.tif", crs=None)

    _, src_crs, *_ = raster_io.load_to_numpy(tmp_path / "nocrs.tif", src_crs=2154)

    assert src_crs.to_epsg() == 2154


@pytest.mark.parametrize("crs_like", ["EPSG:2154", 2154])
def test_load_to_numpy_reads_the_crs_given_as_text_or_code(tmp_path: Path, crs_like) -> None:
    _dem(tmp_path / "nocrs.tif", crs=None)

    _, src_crs, *_ = raster_io.load_to_numpy(
        tmp_path / "nocrs.tif", src_crs=crs_like, dst_crs=crs_like
    )

    assert src_crs.to_epsg() == 2154


def test_a_polygon_layer_is_burnt_onto_the_reference_grid(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    cell = box(
        ORIGIN_X, ORIGIN_Y - 2 * CELL, ORIGIN_X + 2 * CELL, ORIGIN_Y
    )  # 2 x 2 cells, top left
    layer = gpd.GeoDataFrame(geometry=[cell], crs="EPSG:2154")

    values, src_crs, _, nodata = raster_io.load_to_numpy(
        layer, base_path=str(tmp_path / "base.tif")
    )

    burnt = values == 1
    assert burnt.sum() == 4
    assert burnt[:2, :2].all()
    assert (values[~burnt] == nodata).all()
    assert src_crs.to_epsg() == 2154


def test_a_layer_without_crs_takes_the_source_crs_given(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    cell = box(ORIGIN_X, ORIGIN_Y - CELL, ORIGIN_X + CELL, ORIGIN_Y)
    layer = gpd.GeoDataFrame(geometry=[cell])

    values, *_ = raster_io.load_to_numpy(
        layer, src_crs="EPSG:2154", base_path=str(tmp_path / "base.tif")
    )

    assert (values == 1).sum() == 1


def test_a_shapefile_is_read_then_burnt_like_a_layer(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    cell = box(ORIGIN_X, ORIGIN_Y - CELL, ORIGIN_X + CELL, ORIGIN_Y)
    gpd.GeoDataFrame(geometry=[cell], crs="EPSG:2154").to_file(tmp_path / "zone.shp")

    values, *_ = raster_io.load_to_numpy(
        str(tmp_path / "zone.shp"), base_path=str(tmp_path / "base.tif")
    )

    assert (values == 1).sum() == 1


def test_a_coordinate_csv_becomes_points_in_the_returned_frame(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    csv = tmp_path / "points.csv"
    csv.write_text(f"id;x;y\n1;{ORIGIN_X + 50};{ORIGIN_Y - 50}\n", encoding="utf-8")

    values, *_ = raster_io.load_to_numpy(
        str(csv), src_crs="EPSG:2154", base_path=str(tmp_path / "base.tif")
    )

    assert values.shape == (4, 5)


@pytest.mark.parametrize(
    "situation",
    ["vector without reference grid", "layer without any crs", "csv without x and y"],
)
def test_load_to_numpy_gives_up_with_none_when_it_cannot_place_the_data(
    tmp_path: Path, situation: str
) -> None:
    _dem(tmp_path / "base.tif")
    cell = box(ORIGIN_X, ORIGIN_Y - CELL, ORIGIN_X + CELL, ORIGIN_Y)
    if situation == "vector without reference grid":
        result = raster_io.load_to_numpy(gpd.GeoDataFrame(geometry=[cell], crs="EPSG:2154"))
    elif situation == "layer without any crs":
        result = raster_io.load_to_numpy(
            gpd.GeoDataFrame(geometry=[cell]), base_path=str(tmp_path / "base.tif")
        )
    else:
        csv = tmp_path / "bad.csv"
        csv.write_text("a;b\n1;2\n", encoding="utf-8")
        with pytest.raises(Exception):  # the unread csv falls through to rasterio  # noqa: B017
            raster_io.load_to_numpy(str(csv), base_path=str(tmp_path / "base.tif"))
        return

    assert result is None


def test_a_raster_without_crs_cannot_be_reprojected_onto_another_grid(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    fine = _profile(8, 10, crs=None)
    fine["transform"] = from_origin(ORIGIN_X, ORIGIN_Y, CELL / 2, CELL / 2)
    raster_io.write_band(tmp_path / "fine.tif", np.zeros((8, 10), "float32"), fine)

    result = raster_io.load_to_numpy(tmp_path / "fine.tif", base_path=str(tmp_path / "base.tif"))

    assert result is None


def test_load_to_numpy_can_write_what_it_loaded(tmp_path: Path) -> None:
    expected = _dem(tmp_path / "dem.tif")

    raster_io.load_to_numpy(tmp_path / "dem.tif", out_path=str(tmp_path / "copy.tif"))

    with rasterio.open(tmp_path / "copy.tif") as copy:
        np.testing.assert_array_equal(copy.read(1), expected)


# ---- load_to_xarray --------------------------------------------------------


def _dataset(crs: str | None = "EPSG:2154") -> xr.Dataset:
    x = ORIGIN_X + CELL * (np.arange(5) + 0.5)
    y = ORIGIN_Y - CELL * (np.arange(4) + 0.5)
    ds = xr.Dataset(
        {"h": (("y", "x"), np.arange(20, dtype="float64").reshape(4, 5))},
        coords={"x": x, "y": y},
    )
    ds.x.attrs["units"] = "m"
    if crs:
        ds = ds.rio.write_crs(crs)
    return ds


def test_a_geographic_dataset_gets_longitude_and_latitude_attributes() -> None:
    ds = _dataset("EPSG:4326")
    ds.x.attrs["units"] = "degrees_east"
    ds = ds.assign_coords(longitude=("x", ds.x.values), latitude=("y", ds.y.values))

    out = raster_io.load_to_xarray(ds)

    assert out.longitude.attrs["units"] == "degrees_east"
    assert out.latitude.attrs["units"] == "degrees_north"


def test_a_dataset_without_crs_receives_the_source_crs_given() -> None:
    out = raster_io.load_to_xarray(_dataset(crs=None), src_crs=2154)

    assert out.rio.crs.to_epsg() == 2154


def test_a_dataset_is_reprojected_to_the_crs_asked() -> None:
    out = raster_io.load_to_xarray(_dataset(), dst_crs="EPSG:27572")  # Lambert II etendu

    assert out.rio.crs.to_epsg() == 27572
    assert out.x.attrs["units"] == "Meter"


def test_a_dataset_is_reprojected_to_geographic_coordinates() -> None:
    out = raster_io.load_to_xarray(_dataset(), dst_crs="EPSG:4326")

    assert 0.0 < float(out.x.mean()) < 10.0  # Lambert-93 easting 700 km is about 3 degrees east
    assert out.x.attrs == {"long_name": "longitude", "units": "degrees_east"}
    assert out.y.attrs == {"long_name": "latitude", "units": "degrees_north"}


def test_a_raster_on_a_reference_grid_without_crs_is_refused(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif", crs=None)
    _dem(tmp_path / "dem.tif")

    result = raster_io.load_to_numpy(tmp_path / "dem.tif", base_path=str(tmp_path / "base.tif"))

    assert result is None


def test_a_dataset_without_any_crs_cannot_be_reprojected() -> None:
    assert raster_io.load_to_xarray(_dataset(crs=None), dst_crs=4326) is None


def test_a_dataset_is_resampled_onto_the_reference_grid(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    ds = _dataset()
    ds = ds.rio.reproject("EPSG:2154", resolution=CELL / 2)

    out = raster_io.load_to_xarray(ds, base_path=str(tmp_path / "base.tif"))

    assert out.h.shape == (4, 5)


def test_a_dataset_without_crs_cannot_be_put_on_a_reference_grid(tmp_path: Path) -> None:
    _dem(tmp_path / "base.tif")
    ds = _dataset(crs=None).rio.write_transform(from_origin(0, 0, 1, 1))

    assert raster_io.load_to_xarray(ds, base_path=str(tmp_path / "base.tif")) is None


def test_a_geotiff_is_loaded_as_a_flat_dataset_with_the_variable_name_asked(tmp_path: Path) -> None:
    expected = _dem(tmp_path / "dem.tif")

    ds = raster_io.load_to_xarray(str(tmp_path / "dem.tif"), main_var="elevation")

    np.testing.assert_array_equal(ds["elevation"].values, expected)
    assert "band" not in ds.dims


def test_a_netcdf_round_trips_through_the_loader(tmp_path: Path) -> None:
    ds = _dataset()
    ds.to_netcdf(tmp_path / "h.nc")

    out = raster_io.load_to_xarray(str(tmp_path / "h.nc"))

    np.testing.assert_array_equal(out.h.values, ds.h.values)


@pytest.mark.parametrize(
    ("units", "first_value", "expected_first"),
    [
        ("days since 2000-01-01", 0, "2000-01-01"),
        ("months since 2000-01-01", 0, "2000-01-01"),
        ("jours since 01/02/2001", 0, "2001-02-01"),
    ],
)
def test_a_netcdf_with_unreadable_time_units_is_read_by_hand(
    tmp_path: Path, monkeypatch, units: str, first_value: int, expected_first: str
) -> None:
    ds = _dataset()
    ds = ds.expand_dims(time=[first_value, first_value + 1, first_value + 2])
    ds["time"].attrs["units"] = units
    ds.to_netcdf(tmp_path / "t.nc", encoding={"time": {"dtype": "int64"}})
    real_open = xr.open_dataset

    def fail_on_time_decoding(path, **kwargs):
        if kwargs.get("decode_times", True):
            raise ValueError("cannot decode time")
        return real_open(path, **kwargs)

    monkeypatch.setattr(xr, "open_dataset", fail_on_time_decoding)

    out = raster_io.load_to_xarray(str(tmp_path / "t.nc"))

    assert str(out.time.values[0])[:10] == expected_first
    assert len(out.time) == 3


def test_a_netcdf_with_unreadable_time_and_no_unit_is_refused_with_none(
    tmp_path: Path, monkeypatch
) -> None:
    _dataset().expand_dims(time=[0, 1]).to_netcdf(tmp_path / "t.nc")
    real_open = xr.open_dataset

    def fail_on_time_decoding(path, **kwargs):
        if kwargs.get("decode_times", True):
            raise ValueError("cannot decode time")
        return real_open(path, **kwargs)

    monkeypatch.setattr(xr, "open_dataset", fail_on_time_decoding)

    assert raster_io.load_to_xarray(str(tmp_path / "t.nc")) is None


def test_a_file_of_an_unsupported_kind_is_refused_with_none(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    assert raster_io.load_to_xarray(str(tmp_path / "notes.txt")) is None
