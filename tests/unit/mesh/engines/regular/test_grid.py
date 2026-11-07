"""The shape, pitch and vertices of the regular grid, bit for bit the flopy ones."""

from __future__ import annotations

import math

import flopy
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.engines.regular.grid import GridLayout, plan_layout, quad_mesh
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.request import RasterGridSpec
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request, regular_mesh
from tests._helpers.regular_cell_meshes import from_flopy_structured

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


def test_the_vertices_equal_the_flopy_structured_grid_to_the_bit(dem_grid) -> None:
    grid = dem_grid
    cell_mesh = RegularMeshEngine().build(mesh_request(grid, nominal_size_m=max(grid.dx, grid.dy)))
    reference = _flopy_grid(grid)
    legacy = from_flopy_structured(reference)

    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 0], reference.xvertices.reshape(-1))
    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 1], reference.yvertices.reshape(-1))
    np.testing.assert_array_equal(cell_mesh.mesh.flat_connectivity, legacy.flat_connectivity)
    assert cell_mesh.structured_shape == (grid.nrow, grid.ncol)


def test_the_quads_are_the_ones_of_the_regular_grid_wrapper() -> None:
    layout = plan_layout(grid_spec(5, 10, 100.0), 100.0, {})
    wrapper = regular_mesh(5, 10, dx=100.0).mesh

    mesh = quad_mesh(layout)

    np.testing.assert_array_equal(mesh.vertices, wrapper.vertices)
    np.testing.assert_array_equal(mesh.flat_connectivity, wrapper.flat_connectivity)
    assert mesh.cell_types == (CellType.QUADRILATERAL,)


# --------------------------------------------------------------------------- #
# Shape and pitch
# --------------------------------------------------------------------------- #


def test_the_native_pitch_is_the_dem_pitch() -> None:
    layout = plan_layout(DEM, DEM.dx, {})

    assert (layout.nrow, layout.ncol) == (DEM.nrow, DEM.ncol)
    assert (layout.dx, layout.dy) == (DEM.dx, DEM.dy)
    assert layout.native


def test_a_coarser_size_rounds_the_shape_and_spans_the_dem_bounds() -> None:
    layout = plan_layout(DEM, 130.0, {})
    mesh = quad_mesh(layout)

    assert (layout.nrow, layout.ncol) == (5, 8)
    assert layout.dx == (DEM.xmax - DEM.xmin) / 8
    assert layout.dy == (DEM.ymax - DEM.ymin) / 5
    assert mesh.bounds() == (DEM.xmin, DEM.ymin, DEM.xmax, DEM.ymax)
    assert not layout.native


def test_a_size_coarser_than_the_dem_gives_at_least_one_cell() -> None:
    layout = plan_layout(DEM, 5000.0, {})

    assert (layout.nrow, layout.ncol) == (1, 1)
    assert quad_mesh(layout).bounds() == (DEM.xmin, DEM.ymin, DEM.xmax, DEM.ymax)


def test_the_shape_option_fixes_the_shape() -> None:
    layout = _layout(DEM, DEM.dx, {"shape": [3, 7]})

    assert (layout.nrow, layout.ncol) == (3, 7)
    assert layout.dx == (DEM.xmax - DEM.xmin) / 7


@pytest.mark.parametrize("dem_grid", ["pixels_not_square"], indirect=True)
@pytest.mark.parametrize("options", [{}, {"shape": [37, 41]}], ids=["by_size", "by_shape"])
def test_the_dem_shape_keeps_the_dem_pitch_of_pixels_that_are_not_square(dem_grid, options) -> None:
    grid = dem_grid

    layout = _layout(grid, max(grid.dx, grid.dy), options)

    assert (layout.nrow, layout.ncol) == (grid.nrow, grid.ncol)
    assert (layout.dx, layout.dy) == (grid.dx, grid.dy)
    assert layout.native


@pytest.mark.parametrize("dem_grid", ["odd_pitch_negative_origin"], indirect=True)
def test_the_resampled_pitch_is_the_one_of_surface_resample_to_shape(dem_grid) -> None:
    grid = dem_grid
    support = RasterSupport(
        crs="EPSG:2154",
        dx=grid.dx,
        dy=grid.dy,
        xmin=grid.xmin,
        xmax=grid.xmax,
        ymin=grid.ymin,
        ymax=grid.ymax,
        nrows=grid.nrow,
        ncols=grid.ncol,
        nodata=-9999.0,
    )
    resampled = Surface("top", np.zeros((grid.nrow, grid.ncol)), support).resample_to_shape(
        10, 12, resampling="bilinear"
    )
    from_support = RasterGridSpec.from_raster_support(support, crs_wkt=LAMBERT93_WKT)

    layout = _layout(from_support, from_support.dx, {"shape": [10, 12]})

    assert layout.dx == resampled.support.dx
    assert layout.dy == resampled.support.dy


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
