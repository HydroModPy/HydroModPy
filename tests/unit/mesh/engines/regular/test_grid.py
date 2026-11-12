"""The regular grid planned for a DEM (m): shape, pitch and bounds.

A grid is never finer than the DEM and always spans the DEM bounds.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.regular.grid import GridLayout, plan_layout, quad_mesh
from hydromodpy.mesh.request import RasterGridSpec
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request

DEM = grid_spec(12, 20, 50.0, crs_wkt=LAMBERT93_WKT)
"""A 1 km by 600 m DEM at 50 m."""


def _layout(grid: RasterGridSpec, size: float) -> GridLayout:
    """The layout a request asks for, its options frozen as the request freezes them."""
    request = mesh_request(grid, nominal_size_m=size)
    return plan_layout(request.grid, request.nominal_size_m, request.options)


@settings(max_examples=50, deadline=None, derandomize=True)
@given(
    nrow=st.integers(1, 60),
    ncol=st.integers(1, 60),
    pixel=st.floats(1.0, 100.0),
    coarsening=st.floats(1.0, 20.0),
    xmin=st.floats(-1.0e6, 1.0e6),
    ymin=st.floats(-1.0e6, 7.0e6),
)
def test_grid_on_the_dem_bounds(
    nrow: int, ncol: int, pixel: float, coarsening: float, xmin: float, ymin: float
) -> None:
    # Any size from the DEM pitch up gives a grid on the DEM bounds.
    grid = grid_spec(nrow, ncol, pixel, xmin=xmin, ymin=ymin)
    layout = plan_layout(grid, coarsening * pixel, {})
    bounds = quad_mesh(layout).bounds()
    extent = max(grid.xmax - grid.xmin, grid.ymax - grid.ymin)

    assert layout.nrow >= 1 and layout.ncol >= 1
    assert layout.native == ((layout.nrow, layout.ncol) == (grid.nrow, grid.ncol))
    for got, wanted in zip(bounds, (grid.xmin, grid.ymin, grid.xmax, grid.ymax), strict=True):
        assert math.isclose(got, wanted, rel_tol=1.0e-12, abs_tol=1.0e-9 * extent)


REFUSALS = [
    pytest.param(25.0, "cannot mesh finer than the DEM", id="finer than the DEM"),
]


@pytest.mark.parametrize(("size_m", "message"), REFUSALS)
def test_refusals(size_m: float, message: str) -> None:
    with pytest.raises(MeshRequestError, match=message):
        _layout(DEM, size_m)
