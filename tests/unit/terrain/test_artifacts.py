"""Terrain products read back from disk.

A river past the float32 bound (1.9 million cells in example 04) must not stop an
outlet whose snap window holds far fewer cells.
"""

from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import pytest

from hydromodpy.spatial.terrain.artifacts import boundary_area_m2, is_stream_cell, raster_max_near
from tests._helpers.geotiffs import write_geotiff

FAR, NEAR, OFF = (105.0, 895.0), (945.0, 500.0), (-5000.0, -5000.0)


@pytest.fixture
def accumulation(tmp_path):
    """A 100 x 100 ln accumulation of 10 m cells with one big river in column 95."""
    values = np.full((100, 100), math.log(50.0))
    values[:, 95] = math.log(2.0e6)
    values[:10, :10] = -9999.0
    return write_geotiff(
        tmp_path / "dem_acc.tif", values, origin=(0.0, 1000.0), cell=10.0, nodata=-9999.0,
        dtype="float32",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("points", "expected"),
    [([FAR], 50.0), ([NEAR], 2.0e6), ([FAR, NEAR], 2.0e6), ([OFF], math.nan), ([(20.0, 980.0)], math.nan)],
    ids=["a_far_river_does_not_count", "a_near_river_counts", "union_of_outlets", "off_the_raster", "on_nodata_only"],
)  # fmt: skip
def test_the_window_max_reads_only_what_the_snap_would_rank(accumulation, points, expected) -> None:
    near = raster_max_near(accumulation, points, 20.0)
    if math.isnan(expected):
        assert math.isnan(near)
    else:
        assert near == pytest.approx(math.log(expected), rel=1e-6)


def test_a_stream_cell_is_a_positive_cell_on_the_raster(tmp_path) -> None:
    values = np.array([[0.0, 1.0], [-9999.0, 2.0]])
    streams = write_geotiff(tmp_path / "streams.tif", values, cell=10.0, nodata=-9999.0)
    answers = [is_stream_cell(streams, x, y) for x, y in [(5, 15), (15, 15), (5, 5), (15, 5)]]
    assert answers == [False, True, False, True]
    assert not is_stream_cell(streams, -50.0, 5.0)


def test_an_empty_boundary_has_no_area(tmp_path) -> None:
    path = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=[], crs="EPSG:2154").to_file(path)
    assert boundary_area_m2(path) == 0.0
