"""The shape, pitch and vertices of the regular grid, bit for bit the flopy ones."""

from __future__ import annotations

import math

import flopy
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


def _layout(grid: RasterGridSpec, size: float, options: dict | None = None) -> GridLayout:
    """The layout a request asks for, its options frozen as the request freezes them."""
    request = mesh_request(grid, nominal_size_m=size, options=options or {})
    return plan_layout(request.grid, request.nominal_size_m, request.options)


def _flopy_grid(grid: RasterGridSpec) -> flopy.discretization.StructuredGrid:
    return flopy.discretization.StructuredGrid(
        delc=np.full(grid.nrow, grid.dy),
        delr=np.full(grid.ncol, grid.dx),
        xoff=grid.xmin,
        yoff=grid.ymin,
    )


# --------------------------------------------------------------------------- #
# Shape and pitch
# --------------------------------------------------------------------------- #


@settings(max_examples=50, deadline=None, derandomize=True)
@given(
    nrow=st.integers(1, 60),
    ncol=st.integers(1, 60),
    pixel=st.floats(1.0, 100.0),
    coarsening=st.floats(1.0, 20.0),
    xmin=st.floats(-1.0e6, 1.0e6),
    ymin=st.floats(-1.0e6, 7.0e6),
)
def test_any_size_from_the_dem_pitch_up_gives_a_grid_on_the_dem_bounds(
    nrow: int, ncol: int, pixel: float, coarsening: float, xmin: float, ymin: float
) -> None:
    grid = grid_spec(nrow, ncol, pixel, xmin=xmin, ymin=ymin)
    layout = plan_layout(grid, coarsening * pixel, {})
    bounds = quad_mesh(layout).bounds()
    extent = max(grid.xmax - grid.xmin, grid.ymax - grid.ymin)

    assert layout.nrow >= 1 and layout.ncol >= 1
    assert layout.native == ((layout.nrow, layout.ncol) == (grid.nrow, grid.ncol))
    for got, wanted in zip(bounds, (grid.xmin, grid.ymin, grid.xmax, grid.ymax), strict=True):
        assert math.isclose(got, wanted, rel_tol=1.0e-12, abs_tol=1.0e-9 * extent)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


def test_a_grid_finer_than_the_dem_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="cannot mesh finer than the DEM"):
        _layout(DEM, 25.0, {})
