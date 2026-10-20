"""BEDREG: the bed fit reads the channel inside the domain window, not the whole grid."""

from __future__ import annotations

import numpy as np
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic.core.bed_regularization_raster import (
    WINDOW_MARGIN_M,
    restrict_to_window,
)


def test_channel_pixels_outside_the_window_are_dropped() -> None:
    transform = from_origin(0.0, 10_000.0, 10.0, 10.0)  # 1000 x 1000 pixels of 10 m
    channel = np.ones((1000, 1000), dtype=bool)
    bounds = (4000.0, 4000.0, 5000.0, 5000.0)

    kept = restrict_to_window(channel, transform, bounds, margin_m=0.0)

    assert kept.sum() == 100 * 100
    assert kept[500, 450]
    assert not kept[0, 0]
    assert channel.all()  # the input is left alone


def test_the_margin_widens_the_window() -> None:
    transform = from_origin(0.0, 10_000.0, 10.0, 10.0)
    channel = np.ones((1000, 1000), dtype=bool)
    bounds = (4000.0, 4000.0, 5000.0, 5000.0)

    kept = restrict_to_window(channel, transform, bounds, margin_m=100.0)

    assert kept.sum() == 120 * 120
    assert WINDOW_MARGIN_M > 0


def test_a_window_off_the_grid_keeps_nothing() -> None:
    transform = from_origin(0.0, 10_000.0, 10.0, 10.0)
    channel = np.ones((1000, 1000), dtype=bool)

    kept = restrict_to_window(channel, transform, (50_000.0, 0.0, 60_000.0, 1000.0), margin_m=0.0)

    assert not kept.any()


def test_the_window_covers_the_buffered_domain(tmp_path) -> None:
    from types import SimpleNamespace

    import geopandas as gpd
    from shapely.geometry import box

    from hydromodpy.spatial.geographic.core.bed_regularization_raster import _domain_bounds

    gpd.GeoDataFrame(geometry=[box(4000, 4000, 5000, 5000)], crs="EPSG:2154").to_file(
        tmp_path / "watershed.shp"
    )
    gpd.GeoDataFrame(geometry=[box(500, 500, 8500, 8500)], crs="EPSG:2154").to_file(
        tmp_path / "watershed_box_buff.shp"
    )
    paths = SimpleNamespace(
        watershed_shp=str(tmp_path / "watershed.shp"),
        box_buff=str(tmp_path / "watershed_box_buff.shp"),
        geographic_path=str(tmp_path),
    )

    bounds = _domain_bounds(SimpleNamespace(paths=paths))

    assert bounds == (500.0, 500.0, 8500.0, 8500.0)


def test_without_the_buffered_files_the_window_is_the_watershed(tmp_path) -> None:
    from types import SimpleNamespace

    import geopandas as gpd
    from shapely.geometry import box

    from hydromodpy.spatial.geographic.core.bed_regularization_raster import _domain_bounds

    gpd.GeoDataFrame(geometry=[box(4000, 4000, 5000, 5000)], crs="EPSG:2154").to_file(
        tmp_path / "watershed.shp"
    )
    paths = SimpleNamespace(
        watershed_shp=str(tmp_path / "watershed.shp"), box_buff=None, geographic_path=str(tmp_path)
    )

    assert _domain_bounds(SimpleNamespace(paths=paths)) == (4000.0, 4000.0, 5000.0, 5000.0)
