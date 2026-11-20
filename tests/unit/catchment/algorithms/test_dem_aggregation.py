"""``[geographic.catchment].dem_resolution`` aggregates the DEM before any delineation."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine

from hydromodpy.catchment.algorithms.dem_aggregation import aggregate_dem
from tests._helpers.geotiffs import write_geotiff

NODATA = -9999.0


def test_coarse_cell_mean(tmp_path: Path) -> None:
    values = np.arange(100, dtype=float).reshape(10, 10)
    values[1, 1] = NODATA
    dem = write_geotiff(tmp_path / "dem.tif", values, cell=100.0, nodata=NODATA, dtype="float32")
    out = aggregate_dem(dem, tmp_path / "dem_300m.tif", resolution_m=300.0)
    with rasterio.open(out) as src:
        assert (src.height, src.width) == (4, 4)
        assert src.transform.a == 300.0 and src.transform.e == -300.0
        assert (src.transform.c, src.transform.f) == (0.0, 1000.0)
        assert src.crs.to_epsg() == 2154
        assert src.nodata == NODATA
        coarse = src.read(1)
    block = values[:3, :3]
    assert coarse[0, 0] == pytest.approx(block[block != NODATA].mean(), rel=1e-6)
    assert coarse[1, 1] == pytest.approx(values[3:6, 3:6].mean(), rel=1e-6)
    # The last row and column are partial blocks: one fine row, one fine column.
    assert coarse[3, 3] == pytest.approx(values[9, 9], rel=1e-6)
    assert coarse[3, 0] == pytest.approx(values[9, :3].mean(), rel=1e-6)


def test_nan_left_out_of_the_mean(tmp_path) -> None:
    values = np.ones((4, 4), dtype="float32")
    values[0, 0] = np.nan
    dem = write_geotiff(tmp_path / "dem.tif", values, cell=100.0, nodata=None)
    with rasterio.open(aggregate_dem(dem, tmp_path / "out.tif", resolution_m=200.0)) as src:
        coarse = src.read(1)
    np.testing.assert_allclose(coarse, 1.0)


def _rotated(tmp_path: Path) -> Path:
    path = tmp_path / "rotated.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
        crs="EPSG:2154", transform=Affine(100.0, 10.0, 0.0, 10.0, -100.0, 400.0),
    ) as dst:  # fmt: skip
        dst.write(np.ones((4, 4), "float32"), 1)
    return path


@pytest.mark.parametrize(
    ("dem", "resolution", "reason"),
    [
        (lambda t: write_geotiff(t / "dem.tif", np.ones((10, 10)), cell=100.0), 50.0, "finer than"),
        (lambda t: write_geotiff(t / "dem.tif", np.ones((10, 10)), cell=100.0), 0.0, "positive"),
        (_rotated, 300.0, "rotated DEM"),
    ],
    ids=["finer than the pixel", "zero", "rotated"],
)
def test_refusals(tmp_path, dem, resolution, reason):
    with pytest.raises(ValueError, match=reason):
        aggregate_dem(dem(tmp_path), tmp_path / "out.tif", resolution_m=resolution)
