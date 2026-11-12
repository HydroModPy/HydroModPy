"""Side, river and label cells of a cell mesh, and where its side heads sit.

A regular grid gives its sides by row and column arithmetic. A triangulation and a
Voronoi dual give the cells that own a face of the family. The helpers are checked on a
7 x 5 grid, on the island triangulation and its dual, and on the other committed bundles.

The QA says where the side heads sit relative to the side: half a cell inside on a
regular grid, inside the triangle on triangles, on the side on a mesh centered on its
generators. The number is the median distance from the center of each side cell to its
side, measured here from the side cells and the centers.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.mesh.cells.boundary import (
    SIDE_IDS,
    SIDE_OFFSET_KEY,
    annotate_side_cells,
    label_cells,
    side_cells,
    side_center_offset_m,
    stream_cells,
)
from hydromodpy.mesh.engines.regular import engine as regular_engine
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import LineFamilySpec, MeshRequest
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual, bundle_triangles
from tests._helpers.dual_of_triangles import dual_of_the_triangles
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request

NROW, NCOL = 7, 5
RECTANGLE = BUNDLE_CASES[2]
"""A bundle whose domain is a rectangle, so that it has the four sides."""


def _request(*, nrow: int, ncol: int, size: float, lines=()) -> MeshRequest:
    grid = grid_spec(nrow, ncol, size, xmin=1000.25, ymin=2000.5, crs_wkt=LAMBERT93_WKT)
    return mesh_request(grid, lines=lines)


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


STATEMENT = "side heads sit here"


def _grid(*, nrow: int, ncol: int, size: float):
    grid = grid_spec(nrow, ncol, size, xmin=1000.25, ymin=2000.5)
    return RegularMeshEngine().build(mesh_request(grid))


def _offsets_by_hand(cell_mesh) -> np.ndarray:
    """Distance of the centers of the side cells to the side of the vertex box."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    edges = {
        "west_side": (0, vertices[:, 0].min()),
        "east_side": (0, vertices[:, 0].max()),
        "south_side": (1, vertices[:, 1].min()),
        "north_side": (1, vertices[:, 1].max()),
    }
    out = []
    for side, (axis, edge) in edges.items():
        cells = side_cells(cell_mesh, side)
        out.append(np.abs(cell_mesh.centers[cells, axis] - edge))
    return np.concatenate(out)


def test_the_side_cells_of_a_grid_sit_half_a_cell_inside() -> None:
    grid = _grid(nrow=7, ncol=5, size=10.0)

    offsets = side_center_offset_m(grid)

    assert offsets.size == 2 * 7 + 2 * 5
    assert np.allclose(offsets, 5.0)


@pytest.mark.parametrize("producer", [bundle_triangles, bundle_dual])
def test_the_offset_of_a_bundle_mesh_is_the_one_measured_by_hand(producer) -> None:
    cell_mesh = producer(RECTANGLE)

    expected = _offsets_by_hand(cell_mesh)

    assert np.allclose(np.sort(side_center_offset_m(cell_mesh)), np.sort(expected), atol=1.0e-6)


def test_the_regular_engine_states_the_half_cell_in_its_qa() -> None:
    grid = _grid(nrow=7, ncol=5, size=10.0)

    assert grid.qa.extras[SIDE_OFFSET_KEY] == pytest.approx(5.0)
    assert grid.qa.extras["dx_m"] == 10.0
    assert grid.qa.notes[-1] == regular_engine._SIDE_STATEMENT


def test_the_annotation_adds_the_statement_and_the_median() -> None:
    triangles = bundle_triangles(RECTANGLE)
    assert SIDE_OFFSET_KEY not in triangles.qa.extras

    annotated = annotate_side_cells(triangles, STATEMENT)

    assert annotated.qa.notes == (*triangles.qa.notes, STATEMENT)
    assert annotated.qa.extras[SIDE_OFFSET_KEY] == pytest.approx(
        float(np.median(side_center_offset_m(triangles)))
    )
    assert triangles.qa.notes[-1:] != (STATEMENT,)


def _without_faces(cell_mesh):
    return replace(cell_mesh, face_families=None)
