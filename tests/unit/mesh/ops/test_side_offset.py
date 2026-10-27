"""The QA of a cell mesh says where its side heads sit relative to the side.

Half a cell inside on a regular grid, inside the triangle on triangles, on the side on
a mesh centred on its generators. The number is the median distance from the centre of
each side cell to its side, measured here from the side cells and the centres.
"""

from __future__ import annotations

from dataclasses import replace
from importlib.util import find_spec

import numpy as np
import pytest

from hydromodpy.spatial.mesh.engines.regular import engine as regular_engine
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.engines.triangle import engine as triangle_engine
from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi import engine as voronoi_engine
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.ops.family_cells import side_cells
from hydromodpy.spatial.mesh.ops.side_offset import (
    SIDE_OFFSET_KEY,
    annotate_side_cells,
    side_center_offset_m,
)
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual, bundle_triangles
from tests._helpers.mesh_cases import grid_spec, mesh_request

RECTANGLE = BUNDLE_CASES[2]
STATEMENT = "side heads sit here"


def _grid(*, nrow: int, ncol: int, size: float):
    grid = grid_spec(nrow, ncol, size, xmin=1000.25, ymin=2000.5)
    return RegularMeshEngine().build(mesh_request(grid))


def _offsets_by_hand(cell_mesh) -> np.ndarray:
    """Distance of the centres of the side cells to the side of the vertex box."""
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


def test_the_side_cells_of_a_dual_are_centred_on_the_side() -> None:
    dual = bundle_dual(RECTANGLE)

    offsets = side_center_offset_m(dual)

    assert offsets.size > 0
    assert float(np.max(offsets)) < 1.0e-6


def test_the_triangles_of_a_side_have_their_centre_inside_the_domain() -> None:
    triangles = bundle_triangles(RECTANGLE)

    assert float(np.median(side_center_offset_m(triangles))) > 0.0


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


def test_the_annotation_does_not_derive_the_geometry_again() -> None:
    triangles = bundle_triangles(RECTANGLE)

    annotated = annotate_side_cells(triangles, STATEMENT)

    assert annotated.geometry is triangles.geometry
    assert annotated.mesh is triangles.mesh


def test_a_mesh_without_a_side_keeps_the_statement_and_has_no_number() -> None:
    triangles = bundle_triangles(BUNDLE_CASES[0])
    no_side = _without_faces(triangles)

    annotated = annotate_side_cells(no_side, STATEMENT)

    assert SIDE_OFFSET_KEY not in annotated.qa.extras
    assert annotated.qa.notes[-1] == STATEMENT


def _without_faces(cell_mesh):
    return replace(cell_mesh, face_families=None)


@pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")
@pytest.mark.parametrize(
    ("engine", "module"),
    [(TriangleMeshEngine, triangle_engine), (VoronoiMeshEngine, voronoi_engine)],
    ids=["triangle", "voronoi"],
)
def test_the_cut_engines_state_where_their_side_heads_sit(engine, module) -> None:
    cell_mesh = engine().build(mesh_request(grid_spec(10, 10, 100.0)))

    assert cell_mesh.qa.notes[-1] == module._SIDE_STATEMENT
    assert SIDE_OFFSET_KEY in cell_mesh.qa.extras
    if engine is VoronoiMeshEngine:
        assert cell_mesh.qa.extras[SIDE_OFFSET_KEY] < 1.0e-6
    else:
        assert cell_mesh.qa.extras[SIDE_OFFSET_KEY] > 0.0
