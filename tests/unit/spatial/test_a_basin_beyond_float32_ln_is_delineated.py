"""BV-1: a basin of more than 1 049 558 cells is delineated, not refused.

The regional accumulation is stored as ln in float32, which cannot order counts
above that bound. The delineation must rank the snap window on raw counts.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic.core.catchment_from_point import extract_catchment_from_point
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.terrain.port import LN_FLOAT32_COLLISION_COUNT

pytestmark = pytest.mark.allow_subprocess

SIZE = 1100  # 1.21 M cells, above the float32 ln bound.


def _tilted_plane(path) -> None:
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    z = 500.0 - 0.5 * rows - 0.4 * cols
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, SIZE * 5.0, 5.0, 5.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(z.astype("float32"), 1)


def test_a_basin_above_the_ln_bound_is_delineated(tmp_path) -> None:
    assert SIZE * SIZE > LN_FLOAT32_COLLISION_COUNT
    dem = tmp_path / "dem.tif"
    _tilted_plane(dem)
    products = build_regional_flow_products(
        dem_init_path=dem, dem_out_dir_path=tmp_path / "flow", dem_correc_type="fill"
    )
    x = (SIZE - 0.5) * 5.0
    y = 0.5 * 5.0
    out = extract_catchment_from_point(
        x_outlet=x,
        y_outlet=y,
        snap_dist=10,
        accumulation=products.accumulation,
        output_dir=tmp_path / "catchment",
    )
    with rasterio.open(out.watershed_tif) as src:
        mask = src.read(1)
        nodata = src.nodata
    inside = int(np.count_nonzero((mask != nodata) & (mask > 0)))
    assert inside > LN_FLOAT32_COLLISION_COUNT
