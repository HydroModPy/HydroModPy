"""A region given as pixels sizes the field like any region: its size inside, a bounded ramp out."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.request import RasterGridSpec
from hydromodpy.spatial.mesh.sizing.size_field import PixelRegion, SizeTerm, build_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'


def _grid(nrow: int = 60, ncol: int = 80, step: float = 10.0) -> RasterGridSpec:
    return RasterGridSpec(
        xmin=0.0,
        xmax=ncol * step,
        ymin=0.0,
        ymax=nrow * step,
        dx=step,
        dy=step,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=_WKT,
    )


def _burnt(region: object, grid: RasterGridSpec) -> np.ndarray:
    return rasterize(
        [(region, 1)],
        out_shape=(grid.nrow, grid.ncol),
        transform=Affine(grid.dx, 0.0, grid.xmin, 0.0, -grid.dy, grid.ymax),
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)


def _field(region: object, grid: RasterGridSpec) -> np.ndarray:
    return build_size_field(
        grid,
        h0=80.0,
        h_floor=10.0,
        terms=[SizeTerm(name="zone", region=region, size_m=20.0, ramp_m=40.0)],
        outside=None,
        max_slope=0.5,
    ).values


def test_the_pixels_a_polygon_touches_give_the_field_of_the_polygon() -> None:
    grid = _grid()
    polygon = box(205.0, 205.0, 395.0, 295.0)

    by_pixels = _field(PixelRegion(mask=_burnt(polygon, grid), grid=grid), grid)

    np.testing.assert_array_equal(by_pixels, _field(polygon, grid))


def test_a_pixel_region_holds_its_size_inside_and_grows_at_the_ramp_outside() -> None:
    grid = _grid()
    mask = np.zeros((grid.nrow, grid.ncol), dtype=bool)
    mask[20:30, 10:15] = True

    values = _field(PixelRegion(mask=mask, grid=grid), grid)

    assert np.all(values[mask] == 20.0)
    # The ramp asks 60 m over 40 m, steeper than max_slope: the slope is 0.5.
    assert values[25, 16] == pytest.approx(20.0 + 0.5 * 20.0)
    assert values[25, 22] == pytest.approx(20.0 + 0.5 * 80.0)
    assert values.max() == 80.0


def test_a_pixel_region_of_another_grid_or_shape_is_refused() -> None:
    grid = _grid()
    with pytest.raises(MeshRequestError, match="shape"):
        PixelRegion(mask=np.ones((3, 3), dtype=bool), grid=grid)
    other = _grid(step=5.0, nrow=120, ncol=160)
    region = PixelRegion(mask=np.ones((other.nrow, other.ncol), dtype=bool), grid=other)
    with pytest.raises(MeshRequestError, match="another grid"):
        _field(region, grid)


def test_an_empty_pixel_region_is_no_term() -> None:
    grid = _grid()
    empty = PixelRegion(mask=np.zeros((grid.nrow, grid.ncol), dtype=bool), grid=grid)

    assert empty.is_empty
    with pytest.raises(MeshRequestError, match="empty region"):
        SizeTerm(name="zone", region=empty, size_m=20.0, ramp_m=40.0)


def test_a_pixel_region_is_frozen() -> None:
    grid = _grid()
    mask = np.zeros((grid.nrow, grid.ncol), dtype=bool)
    region = PixelRegion(mask=mask, grid=grid)
    mask[0, 0] = True

    assert region.is_empty
    with pytest.raises(ValueError):
        region.mask[0, 0] = True
