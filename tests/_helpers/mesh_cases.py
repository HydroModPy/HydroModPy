"""The mesh setups of the tests: CRS, grid, domain, request, planner inputs and meshes.

A test builds its grid, request or planner inputs here instead of writing every
member by hand. Each builder takes keyword overrides for the members a test
cares about and fills the others with plain defaults. The default CRS is
``TEST_CRS_WKT`` of ``tests._helpers.cell_meshes``, any text the code never
parses; ``LAMBERT93_WKT`` is the real one. The fake mesh engine is in
``tests._helpers.fake_engines``; the triangles of a committed bundle and their
dual are in ``tests._helpers.bundle_cell_meshes``. Not public API.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from pyproj import CRS
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.model.regular_grid import RegularGrid, cell_mesh_from_regular_grid
from hydromodpy.spatial.mesh.planning.input_mesh import read_input_triangulation
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from hydromodpy.spatial.mesh.resample import resample_families
from tests._helpers.cell_meshes import TEST_CRS_WKT

__all__ = [
    "L93_ORIGIN",
    "LAMBERT93_WKT",
    "MESH_BUNDLES",
    "bundle_msh",
    "bundle_triangulation",
    "grid_over",
    "grid_spec",
    "mesh_request",
    "planning_inputs",
    "regular_mesh",
    "square_domain",
    "uniform_size_field",
    "voronoi_lake_mesh",
]

LAMBERT93_WKT = CRS.from_epsg(2154).to_wkt()
"""The real Lambert-93 WKT, for a test whose code parses or compares the CRS.

A test whose code never reads the CRS uses ``TEST_CRS_WKT``.
"""

L93_ORIGIN = (350_000.0, 6_780_000.0)
"""A south-west corner at Lambert-93 magnitudes, so round-off is the one of a real project."""

MESH_BUNDLES = Path(__file__).resolve().parents[2] / "validation_cases" / "shared" / "mesh_bundles"
"""The committed mesh bundles of the validation cases, one folder per case."""


def square_domain(side: float, *, x0: float = 0.0, y0: float = 0.0) -> Polygon:
    """Return the square of *side* metres whose south-west corner is ``(x0, y0)``."""
    return box(x0, y0, x0 + side, y0 + side)


def grid_spec(
    nrow: int,
    ncol: int,
    pixel: float = 1.0,
    *,
    xmin: float = 0.0,
    ymin: float = 0.0,
    crs_wkt: str = TEST_CRS_WKT,
) -> RasterGridSpec:
    """Return the grid of ``nrow x ncol`` square pixels whose south-west corner is ``(xmin, ymin)``."""
    return RasterGridSpec(
        xmin=xmin,
        xmax=xmin + ncol * pixel,
        ymin=ymin,
        ymax=ymin + nrow * pixel,
        dx=pixel,
        dy=pixel,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=crs_wkt,
    )


def grid_over(
    area: BaseGeometry | tuple[float, float, float, float],
    pixel: float | None = None,
    *,
    crs_wkt: str = TEST_CRS_WKT,
) -> RasterGridSpec:
    """Return the grid on the exact bounds of *area*, a geometry or a bounds tuple.

    The pixels are squares of *pixel* metres, which must divide both sides. With
    no *pixel* the grid is one cell, for an engine that reads no raster.
    """
    xmin, ymin, xmax, ymax = area.bounds if isinstance(area, BaseGeometry) else area
    if pixel is None:
        dx, dy, nrow, ncol = xmax - xmin, ymax - ymin, 1, 1
    else:
        dx, dy = pixel, pixel
        nrow, ncol = round((ymax - ymin) / pixel), round((xmax - xmin) / pixel)
    return RasterGridSpec(
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        dx=dx,
        dy=dy,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=crs_wkt,
    )


def uniform_size_field(grid: RasterGridSpec, size: float) -> SizeField:
    """Return the size field of *size* metres on every pixel of *grid*."""
    return SizeField(np.full((grid.nrow, grid.ncol), size), grid)


def mesh_request(grid: RasterGridSpec | None = None, **overrides: object) -> MeshRequest:
    """Return a request on *grid*, by default ``grid_spec(10, 10, 100.0)``.

    The domain is the box of the grid, the CRS the one of the grid and the
    nominal size its pixel. *overrides* set any member of ``MeshRequest``.
    """
    grid = grid_spec(10, 10, 100.0) if grid is None else grid
    members: dict[str, object] = {
        "domain": box(grid.xmin, grid.ymin, grid.xmax, grid.ymax),
        "grid": grid,
        "nominal_size_m": grid.dx,
    }
    members.update(overrides)
    return MeshRequest(**members)


def planning_inputs(grid: RasterGridSpec | None = None, **overrides: object) -> PlanningInputs:
    """Return the planner inputs of a bare synthetic domain on *grid*, by default ``grid_spec(10, 10, 100.0)``.

    The domain is the box of the grid and the CRS the one of the grid. There is
    no river, catchment, lake, geology, refinement zone or triangulation, and
    ``synthetic`` is True. *overrides* set any member of ``PlanningInputs``; a
    test that gives a ``watershed`` also gives ``synthetic=False``.
    """
    grid = grid_spec(10, 10, 100.0) if grid is None else grid
    members: dict[str, object] = {
        "dem_grid": grid,
        "domain": box(grid.xmin, grid.ymin, grid.xmax, grid.ymax),
        "river_trace": None,
        "watershed": None,
        "lakes": (),
        "lake_structures": (),
        "geology": None,
        "refinement_zones": (),
        "input_triangulation": None,
        "synthetic": True,
    }
    members.update(overrides)
    return PlanningInputs(**members)


def regular_mesh(
    nrow: int,
    ncol: int,
    *,
    dx: float = 1.0,
    dy: float | None = None,
    xmin: float = 0.0,
    ymin: float = 0.0,
    crs_wkt: str = TEST_CRS_WKT,
) -> PlanarCellMesh:
    """Return the regular cell mesh of ``nrow x ncol`` cells, row 0 north, with no family.

    The cells are ``dx`` by ``dy`` metres (``dy`` defaults to ``dx``) and the
    south-west corner is ``(xmin, ymin)``. The mesh comes from ``RegularGrid``,
    not from the ``regular`` engine, so it carries no ``boundary:*`` family; its
    ``.mesh`` is the quad ``HydroMesh`` of the grid.
    """
    dy = dx if dy is None else dy
    grid = RegularGrid(
        shape=(nrow, ncol), dx=float(dx), dy=float(dy), origin=(xmin, ymin + nrow * dy)
    )
    return cell_mesh_from_regular_grid(grid, crs_wkt=crs_wkt)


def voronoi_lake_mesh(
    lake: Polygon,
    *,
    domain: Polygon,
    pixel: float,
    cell_size: float,
    rivers: Sequence[LineString] = (),
    crs_wkt: str = TEST_CRS_WKT,
) -> PlanarCellMesh:
    """Return the generated Voronoi mesh of *domain* whose faces follow the shore of *lake*.

    The grid lies on the bounds of *domain* with pixels of *pixel* metres, and
    the size field is *cell_size* everywhere. The shore is the exterior ring of
    *lake* as given, in a ``lakes`` face family; pass ``shapely.normalize(lake)``
    for a ring that does not depend on how the polygon was drawn. *rivers*, if
    any, form a ``rivers`` cell family. The lines are resampled on the size field
    as the planner does.
    """
    grid = grid_over(domain, pixel, crs_wkt=crs_wkt)
    field = uniform_size_field(grid, cell_size)
    families = (
        *((LineFamilySpec("rivers", "cell", tuple(rivers)),) if rivers else ()),
        LineFamilySpec("lakes", "face", (LineString(lake.exterior.coords),), closed=True),
    )
    lines = resample_families(families, domain=domain, size_field=field).families
    request = mesh_request(
        grid, domain=domain, nominal_size_m=cell_size, lines=lines, size_field=field
    )
    return VoronoiMeshEngine().build(request)


def bundle_msh(case: str) -> Path:
    """Return the path of the committed ``mesh_2d.msh`` of the bundle *case*."""
    return MESH_BUNDLES / case / "mesh_2d.msh"


def bundle_triangulation(case: str) -> InputTriangulation:
    """Return the triangles and labelled edges of the bundle *case*, as an engine reads them."""
    return read_input_triangulation(bundle_msh(case))
