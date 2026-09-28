"""A delineation refuses a log accumulation only where its outlets snap.

The snap ranks the cells of each outlet's search window. A regional raster whose
main river carries more cells than float32 can tell apart, once stored as a
natural logarithm, does not stop an outlet whose window holds far fewer: the
filled DEM of example 04 drains 1.9 million cells to one river, and its outlet
sits on a tributary.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.spatial.terrain.artifacts import raster_max_near
from hydromodpy.spatial.terrain.port import LN_FLOAT32_COLLISION_COUNT, require_resolvable_counts


def _write(path, values: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 1000.0, 10.0, 10.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(values.astype("float32"), 1)


@pytest.fixture
def accumulation(tmp_path):
    values = np.full((100, 100), math.log(50.0), dtype="float32")
    values[:, 95] = math.log(2.0e6)
    path = tmp_path / "dem_acc.tif"
    _write(path, values)
    return path


def test_a_far_river_does_not_count(accumulation) -> None:
    near = raster_max_near(accumulation, [(105.0, 895.0)], 20.0)

    assert near == pytest.approx(math.log(50.0), rel=1e-6)


def test_a_river_inside_the_window_counts(accumulation) -> None:
    near = raster_max_near(accumulation, [(945.0, 500.0)], 20.0)

    assert near == pytest.approx(math.log(2.0e6), rel=1e-6)


def test_the_window_is_the_union_of_the_outlets(accumulation) -> None:
    near = raster_max_near(accumulation, [(105.0, 895.0), (945.0, 500.0)], 20.0)

    assert near == pytest.approx(math.log(2.0e6), rel=1e-6)


def test_an_outlet_off_the_raster_reads_nothing(accumulation) -> None:
    assert math.isnan(raster_max_near(accumulation, [(-5000.0, -5000.0)], 20.0))


def test_the_guard_refuses_only_what_the_snap_would_rank(accumulation) -> None:
    product = type("Acc", (), {"transform": "ln"})()
    far = raster_max_near(accumulation, [(105.0, 895.0)], 20.0)
    near = raster_max_near(accumulation, [(945.0, 500.0)], 20.0)

    require_resolvable_counts(product, max_stored_value=far, member="delineate")
    assert near >= math.log(LN_FLOAT32_COLLISION_COUNT)
    with pytest.raises(TerrainProductError, match="cannot rank"):
        require_resolvable_counts(product, max_stored_value=near, member="delineate")
