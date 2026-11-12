"""A domain taken straight from the DEM: its valid pixels, its frame and a copy of it."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from hydromodpy.catchment.algorithms.direct_dem_domain import build_direct_dem_domain
from hydromodpy.catchment.algorithms.geographic_paths import build_geographic_paths
from tests._helpers.geotiffs import write_geotiff

NODATA = -9999.0


def _paths(tmp_path: Path):
    paths = build_geographic_paths(tmp_path / "run")
    Path(paths.geographic_path).mkdir(parents=True)
    return paths


def test_domain_footprint(tmp_path) -> None:
    values = np.full((5, 5), 10.0, dtype="float32")
    values[0, :] = NODATA
    values[:, 0] = np.nan
    dem = write_geotiff(tmp_path / "dem.tif", values, cell=100.0, nodata=NODATA)
    paths = _paths(tmp_path)
    products = build_direct_dem_domain(dem_path=dem, paths=paths, crs_project="EPSG:2154")
    # Four by four valid pixels of 100 m.
    assert products.domain_area_km2 == pytest.approx(0.16)
    watershed = gpd.read_file(products.watershed_shp)
    assert watershed.total_bounds.tolist() == [100.0, 0.0, 500.0, 400.0]
    buffered = gpd.read_file(products.watershed_buff_shp).geometry.iloc[0]
    assert buffered.equals(watershed.geometry.iloc[0])
    for frame in (products.watershed_box_shp, products.watershed_box_buff_shp):
        assert gpd.read_file(frame).total_bounds.tolist() == [0.0, 0.0, 500.0, 500.0]
    with rasterio.open(dem) as src, rasterio.open(products.watershed_box_buff_dem) as copy:
        assert copy.transform == src.transform
        assert copy.crs == src.crs
        np.testing.assert_array_equal(copy.read(1), src.read(1))


def test_no_valid_pixel_refused(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.full((3, 3), NODATA), nodata=NODATA)
    with pytest.raises(ValueError, match="at least one valid cell"):
        build_direct_dem_domain(dem_path=dem, paths=_paths(tmp_path))


@pytest.mark.xfail(
    strict=True,
    reason="build_direct_dem_domain measures the footprint in the DEM CRS: on a DEM in "
    "degrees the domain area is in square degrees, not km2.",
)
def test_area_of_a_dem_in_degrees(tmp_path) -> None:
    # 0.01 x 0.01 degree pixels near Rennes, about 0.74 x 1.11 km each.
    ones = np.ones((4, 4), "float32")
    dem = write_geotiff(tmp_path / "dem.tif", ones, origin=(-1.7, 48.1), cell=0.01, crs="EPSG:4326")
    products = build_direct_dem_domain(
        dem_path=dem, paths=_paths(tmp_path), crs_project="EPSG:2154"
    )
    assert products.domain_area_km2 == pytest.approx(16 * 0.74 * 1.11, rel=0.05)
