"""``Surface.shifted_down_by`` must leave the NODATA sentinel where it is.

The support is shared by reference, so it keeps advertising the same ``nodata``
value, and every consumer recognises a no-data cell by exact equality with it.
Shifting the sentinel down turns it into an ordinary elevation: the sampler no
longer masks it, bilinear interpolation blends it with real terrain, and a mesh
cell whose stencil straddles the mask edge inherits an aquifer bottom kilometres
deep with a perfectly clean top and an active idomain.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

_NODATA = -9999.0
_THICKNESS = 35.0


def _masked_topography() -> Surface:
    # 3x3 raster of 1 m pixels; the right column is outside the catchment mask.
    values = np.array(
        [
            [100.0, 100.0, _NODATA],
            [100.0, 100.0, _NODATA],
            [100.0, 100.0, _NODATA],
        ]
    )
    support = RasterSupport(
        crs="EPSG:2154",
        dx=1.0,
        dy=1.0,
        xmin=0.0,
        xmax=3.0,
        ymin=0.0,
        ymax=3.0,
        nrows=3,
        ncols=3,
        nodata=_NODATA,
    )
    return Surface(name="topo", values=values, support=support)


def test_shifted_down_by_keeps_the_sentinel_in_place() -> None:
    top = _masked_topography()
    bottom = top.shifted_down_by(_THICKNESS)
    values = bottom.as_array()
    mask = top.as_array() == _NODATA
    assert np.all(values[mask] == _NODATA)
    # The shifted sentinel (-10034) must appear nowhere: it is what silently
    # becomes an ordinary elevation downstream.
    assert not np.any(values == _NODATA - _THICKNESS)
    assert np.all(values[~mask] == pytest.approx(100.0 - _THICKNESS))
    assert bottom.support.nodata == _NODATA


def test_sampled_thickness_stays_constant_across_the_mask_edge() -> None:
    # A point whose 2x2 stencil straddles the mask edge is exactly where the bug
    # showed: top interpolated over the valid corners only, bottom dragged toward
    # the sentinel. Both surfaces must mask the same pixels, so the thickness is
    # the configured one everywhere a sample is defined at all.
    top = _masked_topography()
    bottom = top.shifted_down_by(_THICKNESS)
    top_sampler = PreparedSurfaceSampler.from_surface(top)
    bottom_sampler = PreparedSurfaceSampler.from_surface(bottom)
    assert int(np.isnan(top_sampler.values).sum()) == int(np.isnan(bottom_sampler.values).sum())

    x = np.linspace(0.05, 2.95, 40)
    y = np.linspace(0.05, 2.95, 40)
    grid_x, grid_y = np.meshgrid(x, y)
    sampled_top = np.asarray(top_sampler.sample(grid_x.ravel(), grid_y.ravel()), dtype=float)
    sampled_bottom = np.asarray(bottom_sampler.sample(grid_x.ravel(), grid_y.ravel()), dtype=float)
    defined = np.isfinite(sampled_top) & np.isfinite(sampled_bottom)
    assert defined.any()
    thickness = sampled_top[defined] - sampled_bottom[defined]
    assert thickness.min() == pytest.approx(_THICKNESS)
    assert thickness.max() == pytest.approx(_THICKNESS)


def test_shift_without_a_nodata_declaration_is_a_plain_subtraction() -> None:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=1.0,
        dy=1.0,
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        nrows=2,
        ncols=2,
        nodata=None,
    )
    top = Surface(name="topo", values=np.array([[10.0, 20.0], [30.0, 40.0]]), support=support)
    shifted = top.shifted_down_by(5.0).as_array()
    assert shifted.ravel().tolist() == pytest.approx([5.0, 15.0, 25.0, 35.0])
