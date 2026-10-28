"""The ``geographic`` group of a run store opens with xarray, nodata, axes and CRS.

The group stored its nodata as a float ``_FillValue`` attribute, which
``xarray.open_zarr`` refuses on a Zarr 3 array, and its rasters had neither
pixel coordinates nor a grid mapping. A run written that way still reads
through HydroModPy.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
import xarray as xr
from pyproj import CRS

from hydromodpy.results.exporters.geotiff import export_geographic_raster
from hydromodpy.results.exporters.vocabulary import _stored_rasters
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

pytestmark = pytest.mark.fast

TRANSFORM = (75.0, 0.0, 385_762.5, 0.0, -75.0, 6_826_612.5)
NODATA = -9999.0


def _dem() -> np.ndarray:
    dem = np.arange(12.0, dtype="float32").reshape(3, 4) + 100.0
    dem[0, 0] = NODATA
    return dem


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "fields.zarr"
    with SimulationZarr.create(path, n_cells=4, n_layers=1) as sz:
        sz.write_geographic_raster(
            "watershed_dem", _dem(), transform=TRANSFORM, crs="EPSG:2154", nodata=NODATA
        )
    return path


def test_xarray_opens_the_group_with_its_nodata_axes_and_crs(store_path: Path):
    ds = xr.open_zarr(store_path, group="geographic", consolidated=False, decode_coords="all")
    dem = ds["watershed_dem"]

    assert np.isnan(dem.values[0, 0])
    assert dem.values[2, 3] == 111.0
    np.testing.assert_allclose(dem["watershed_dem_x"], 385_762.5 + 75.0 * (np.arange(4) + 0.5))
    np.testing.assert_allclose(dem["watershed_dem_y"], 6_826_612.5 - 75.0 * (np.arange(3) + 0.5))
    assert CRS.from_cf(dem["watershed_dem_crs"].attrs).to_epsg() == 2154


def test_the_hydromodpy_reader_reads_a_new_run_and_an_old_one(store_path: Path, tmp_path: Path):
    old_path = tmp_path / "old.zarr"
    with SimulationZarr.create(old_path, n_cells=4, n_layers=1) as sz:
        geo = sz.root.require_group("geographic")
        old = geo.create_array("watershed_dem", data=_dem(), dimension_names=("d0", "d1"))
        old.attrs.update(
            {"transform": list(TRANSFORM), "crs": "EPSG:2154", "nodata": NODATA, "shape": [3, 4]}
        )
        old.attrs["_FillValue"] = NODATA

    for path in (store_path, old_path):
        with SimulationZarr(path) as sz:
            data, meta = sz.read_geographic_raster("watershed_dem")
        np.testing.assert_array_equal(data, _dem())
        assert meta == {
            "transform": TRANSFORM,
            "crs": "EPSG:2154",
            "nodata": NODATA,
            "shape": (3, 4),
        }


def test_only_the_rasters_are_offered_for_export(store_path: Path, tmp_path: Path):
    class _Store:
        def open_zarr(self, _sim_id):
            return SimulationZarr(store_path)

    assert _stored_rasters(_Store(), "run") == ["watershed_dem"]

    tif = export_geographic_raster(store_path, "run", "watershed_dem", tmp_path / "dem.tif")
    with rasterio.open(tif) as src:
        assert src.nodata == NODATA
        assert src.crs.to_epsg() == 2154
        np.testing.assert_array_equal(src.read(1), _dem())


@pytest.mark.parametrize(
    ("values", "transform", "crs", "units"),
    [
        (
            np.array([[1.0, -1.0]], dtype="float32"),
            (0.01, 0.0, -2.0, 0.0, -0.01, 48.0),
            "EPSG:4326",
            ("degrees_east", "degrees_north"),
        ),
        (np.array([[1, -1]], dtype="int16"), TRANSFORM, "EPSG:2154", ("m", "m")),
    ],
    ids=["degrees", "integer"],
)
def test_the_axes_take_the_unit_of_the_crs_and_an_integer_keeps_its_nodata(
    tmp_path: Path, values, transform, crs, units
):
    path = tmp_path / "fields.zarr"
    with SimulationZarr.create(path, n_cells=4, n_layers=1) as sz:
        sz.write_geographic_raster("grid", values, transform=transform, crs=crs, nodata=-1)

    ds = xr.open_zarr(path, group="geographic", consolidated=False, decode_coords="all")

    assert (ds["grid_x"].attrs["units"], ds["grid_y"].attrs["units"]) == units
    assert int(ds["grid"].isnull().sum()) == 1
