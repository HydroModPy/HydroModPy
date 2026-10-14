"""Side, river and label cells of a cell mesh are read from its face families.

A regular grid gives its sides by row and column arithmetic. A triangulation and a
Voronoi dual give the cells that own a face of the family. The helpers are checked on a
7 x 5 grid, on the island triangulation and its dual, and on the other committed bundles.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from importlib.util import find_spec

import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.family_cells import (
    SIDE_IDS,
    label_cells,
    side_cells,
    stream_cells,
)
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual, bundle_triangles
from tests._helpers.dual_of_triangles import dual_of_the_triangles

WKT = CRS.from_epsg(2154).to_wkt()
NROW, NCOL = 7, 5
RECTANGLE = BUNDLE_CASES[2]
"""A bundle whose domain is a rectangle, so that it has the four sides."""


def _request(*, nrow: int, ncol: int, size: float, lines=()) -> MeshRequest:
    xmin, ymin = 1000.25, 2000.5
    xmax, ymax = xmin + ncol * size, ymin + nrow * size
    return MeshRequest(
        domain=box(xmin, ymin, xmax, ymax),
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            dx=size,
            dy=size,
            nrow=nrow,
            ncol=ncol,
            crs_wkt=WKT,
        ),
        nominal_size_m=size,
        lines=lines,
    )


def _grid_side_by_arithmetic(side: str) -> list[int]:
    """The rows and columns the structured branch of ``side_boundary_cell_ids`` listed."""
    if side == "west_side":
        return [row * NCOL for row in range(NROW)]
    if side == "east_side":
        return [row * NCOL + NCOL - 1 for row in range(NROW)]
    if side == "north_side":
        return list(range(NCOL))
    return list(range((NROW - 1) * NCOL, NROW * NCOL))


@pytest.fixture(scope="module")
def grid() -> PlanarCellMesh:
    return RegularMeshEngine().build(_request(nrow=NROW, ncol=NCOL, size=10.0))


@pytest.mark.parametrize("side", SIDE_IDS)
def test_the_sides_of_a_grid_are_its_border_rows_and_columns(grid, side) -> None:
    assert side_cells(grid, side).tolist() == sorted(_grid_side_by_arithmetic(side))


@pytest.mark.parametrize("side", SIDE_IDS)
def test_a_grid_side_is_also_a_label(grid, side) -> None:
    assert np.array_equal(label_cells(grid, side), side_cells(grid, side))


def _cells_of_faces(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """The cells on either side of the faces of one family, read from the face table."""
    table, rows = cell_mesh.face_families, cell_mesh.face_rows(family)
    if table is None:
        return np.empty(0, dtype=np.int64)
    cells = np.concatenate([table.cell_a[rows], table.cell_b[rows]])
    return np.unique(cells[cells >= 0])


@pytest.mark.parametrize("case", BUNDLE_CASES)
def test_a_triangulation_side_holds_the_cells_that_own_its_faces(case) -> None:
    triangles = bundle_triangles(case)
    for side in SIDE_IDS:
        family = f"boundary:{side.removesuffix('_side')}"
        assert np.array_equal(side_cells(triangles, side), _cells_of_faces(triangles, family))
        assert np.array_equal(label_cells(triangles, side), side_cells(triangles, side))


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("producer", [bundle_triangles, bundle_dual])
def test_a_bundle_mesh_has_the_labels_of_its_sides_and_its_river(case, producer) -> None:
    cell_mesh = producer(case)
    for side in SIDE_IDS:
        assert np.array_equal(label_cells(cell_mesh, side), side_cells(cell_mesh, side))
    if cell_mesh.face_rows("rivers").any():
        assert np.array_equal(stream_cells(cell_mesh), _cells_of_faces(cell_mesh, "rivers"))
    else:
        assert stream_cells(cell_mesh).size == 0
    for label in ("stream", "river"):
        assert np.array_equal(label_cells(cell_mesh, label), stream_cells(cell_mesh))


def test_a_dual_side_holds_the_cells_centred_on_it() -> None:
    dual = bundle_dual(RECTANGLE)
    assert dual.center_kind == "generator"
    west = side_cells(dual, "west_side")
    xmin = dual.mesh.vertices[:, 0].min()
    assert west.size > 0
    assert np.allclose(dual.centers[west, 0], xmin, atol=1.0e-6)
    touching = dual.family_cells("boundary:west")
    assert set(west.tolist()) <= set(touching.tolist())


def test_a_side_with_no_centred_cell_falls_back_to_the_cells_with_a_face_on_it(caplog) -> None:
    dual = bundle_dual(RECTANGLE)
    shifted = replace(dual, centers=dual.centers + np.array([0.37, 0.0]))
    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        west = side_cells(shifted, "west_side")
        south = side_cells(shifted, "south_side")
    assert np.array_equal(west, dual.family_cells("boundary:west"))
    assert np.array_equal(south, side_cells(dual, "south_side"))
    assert sum("west_side" in record.getMessage() for record in caplog.records) == 1


def test_a_named_boundary_family_is_a_label(grid) -> None:
    triangles = bundle_triangles(RECTANGLE)
    assert np.array_equal(
        label_cells(triangles, "boundary:west"), triangles.family_cells("boundary:west")
    )
    assert np.array_equal(
        label_cells(triangles, "boundary:west"), side_cells(triangles, "west_side")
    )


def test_an_unknown_label_matches_nothing_and_an_unknown_side_is_refused(grid) -> None:
    assert label_cells(grid, "no_such_label").size == 0
    assert label_cells(grid, "").size == 0
    with pytest.raises(ValueError, match="Unsupported side boundary id"):
        side_cells(grid, "up_side")


def test_a_grid_without_river_has_no_stream_cell(grid) -> None:
    assert stream_cells(grid).size == 0


def test_the_stream_of_a_grid_is_the_cells_of_its_chains() -> None:
    river = LineString([(1005.0, 2060.0), (1025.0, 2035.0), (1044.0, 2005.0)])
    request = _request(
        nrow=NROW, ncol=NCOL, size=10.0, lines=(LineFamilySpec("rivers", "cell", (river,)),)
    )
    cell_mesh = RegularMeshEngine().build(request)
    chains = cell_mesh.chains("rivers")
    assert chains
    expected = np.unique(np.concatenate([chain.cell_ids for chain in chains]))
    assert np.array_equal(stream_cells(cell_mesh), expected)
    assert np.array_equal(label_cells(cell_mesh, "river"), expected)


def _triangles(request: MeshRequest) -> PlanarCellMesh:
    return TriangleMeshEngine().build(request)


def _dual_of_triangles(request: MeshRequest) -> PlanarCellMesh:
    return dual_of_the_triangles(TriangleMeshEngine().build(request), request)


@pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")
@pytest.mark.parametrize("build", [_triangles, _dual_of_triangles])
def test_the_stream_of_a_cut_mesh_is_the_cells_on_both_sides_of_its_faces(build) -> None:
    river = LineString([(100.0, 150.0), (450.0, 420.0), (900.0, 880.0)])
    request = MeshRequest(
        domain=box(0.0, 0.0, 1000.0, 1000.0),
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=0.0,
            xmax=1000.0,
            ymin=0.0,
            ymax=1000.0,
            dx=100.0,
            dy=100.0,
            nrow=10,
            ncol=10,
            crs_wkt=WKT,
        ),
        nominal_size_m=50.0,
        lines=(LineFamilySpec("rivers", "cell", (river,)),),
    )
    cell_mesh = build(request)
    assert stream_cells(cell_mesh).size > 0
    assert np.array_equal(stream_cells(cell_mesh), _cells_of_faces(cell_mesh, "rivers"))
    assert np.array_equal(label_cells(cell_mesh, "stream"), stream_cells(cell_mesh))
