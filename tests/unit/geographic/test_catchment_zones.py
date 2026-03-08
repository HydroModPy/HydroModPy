from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.geometry import Polygon

from hydromodpy.geographic.core.catchment_domain import derive_catchment_domain
from hydromodpy.geographic.core.catchment_zones import (
    CatchmentZoneCode,
    build_catchment_zone_codes,
    build_uniform_zone_codes,
)


def _write_square_catchment(path: Path) -> None:
    gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box(0.0, 0.0, 1000.0, 1000.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(str(path))


def _write_triangle_catchment(path: Path) -> None:
    gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[Polygon([(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0)])],
        crs="EPSG:2154",
    )
    gdf.to_file(str(path))


def _write_reference_raster(path: Path) -> None:
    # Cover [-200, 1200] x [-200, 1200] with 100 m cells.
    transform = from_origin(-200.0, 1200.0, 100.0, 100.0)
    profile = {
        "driver": "GTiff",
        "height": 14,
        "width": 14,
        "count": 1,
        "dtype": rasterio.uint8,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": 0,
    }
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(np.ones((14, 14), dtype=np.uint8), 1)


def _write_dem_reference_raster(path: Path) -> None:
    transform = from_origin(0.0, 300.0, 100.0, 100.0)
    profile = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    values = np.array(
        [
            [-9999.0, 10.0, 11.0],
            [12.0, 13.0, -9999.0],
            [14.0, 15.0, 16.0],
        ],
        dtype=np.float32,
    )
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(values, 1)


def _bounds(path: str | Path) -> tuple[float, float, float, float]:
    gdf = gpd.read_file(str(path))
    xmin, ymin, xmax, ymax = gdf.total_bounds
    return float(xmin), float(ymin), float(xmax), float(ymax)


def test_derive_catchment_domain_with_percent_buffer(tmp_path: Path):
    catchment_path = tmp_path / "watershed.shp"
    out_dir = tmp_path / "out"
    _write_square_catchment(catchment_path)

    products = derive_catchment_domain(
        catchment_path,
        out_dir,
        buff_area=20.0,
        dem_resolution=10.0,
    )

    assert products.catchment_area_km2 == pytest.approx(1.0, abs=1e-12)
    assert products.buffer_distance_m == pytest.approx(200.0, abs=1e-12)

    assert _bounds(products.watershed_box_shp) == pytest.approx((0.0, 0.0, 1000.0, 1000.0), abs=1e-6)
    assert _bounds(products.watershed_buff_shp) == pytest.approx((-200.0, -200.0, 1200.0, 1200.0), abs=1e-6)
    assert _bounds(products.watershed_box_buff_shp) == pytest.approx(
        (-200.0, -200.0, 1200.0, 1200.0),
        abs=1e-6,
    )


def test_derive_catchment_domain_with_explicit_distance(tmp_path: Path):
    catchment_path = tmp_path / "watershed.shp"
    out_dir = tmp_path / "out"
    _write_square_catchment(catchment_path)

    products = derive_catchment_domain(
        catchment_path,
        out_dir,
        buff_area="150",
    )

    assert products.buffer_distance_m == pytest.approx(150.0, abs=1e-12)
    assert _bounds(products.watershed_box_buff_shp) == pytest.approx(
        (-150.0, -150.0, 1150.0, 1150.0),
        abs=1e-6,
    )


def test_build_catchment_zone_codes(tmp_path: Path):
    catchment_path = tmp_path / "watershed.shp"
    out_dir = tmp_path / "out"
    reference_raster = tmp_path / "reference.tif"
    _write_triangle_catchment(catchment_path)
    _write_reference_raster(reference_raster)

    domain_products = derive_catchment_domain(
        catchment_path,
        out_dir,
        buff_area="200",
    )
    zone_codes_path = out_dir / "zone_codes.tif"
    products = build_catchment_zone_codes(
        catchment_shp=catchment_path,
        watershed_buff_shp=domain_products.watershed_buff_shp,
        watershed_box_buff_shp=domain_products.watershed_box_buff_shp,
        reference_raster_path=reference_raster,
        zone_codes_tif_path=zone_codes_path,
    )

    assert products.zone_codes is not None
    assert products.zone_codes_tif is not None
    assert Path(products.zone_codes_tif).exists()

    zone_codes = products.zone_codes
    assert np.any(zone_codes == int(CatchmentZoneCode.DOMAIN_OUTSIDE_BUFFER))
    assert np.any(zone_codes == int(CatchmentZoneCode.BUFFER_RING))
    assert np.any(zone_codes == int(CatchmentZoneCode.CATCHMENT_CORE))


def test_build_uniform_zone_codes(tmp_path: Path):
    reference_raster = tmp_path / "domain_dem.tif"
    zone_codes_path = tmp_path / "zone_codes.tif"
    _write_dem_reference_raster(reference_raster)

    products = build_uniform_zone_codes(
        reference_raster_path=reference_raster,
        zone_codes_tif_path=zone_codes_path,
    )

    assert products.zone_codes_tif is not None
    assert Path(products.zone_codes_tif).exists()
    assert np.all(
        products.zone_codes[
            np.array(
                [
                    [False, True, True],
                    [True, True, False],
                    [True, True, True],
                ],
                dtype=bool,
            )
        ]
        == int(CatchmentZoneCode.UNIFORM)
    )
    assert products.zone_codes[0, 0] == 0
    assert products.zone_codes[1, 2] == 0
