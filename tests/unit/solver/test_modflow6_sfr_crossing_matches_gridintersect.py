"""Without river chains, a reach is shared among the cells it crosses, as GridIntersect shared it.

The SFR builder split a reach line with ``flopy.utils.GridIntersect`` on a
``VertexGrid`` rebuilt from the mesh, dropped the pieces under 1e-6 m and
ordered the cells by the projection of each piece's midpoint. On a mesh that
carries no ``rivers`` chain it now cuts the line at the cell boundaries of the
cell mesh. The two are compared on a regular grid at a non-integer origin, on
the triangles and on the Voronoi dual of a committed bundle: same cells in the
same order, lengths within 1e-9 m.
"""

from __future__ import annotations

import numpy as np
import pytest
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import LineString

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.line_on_chain import crossing_pieces
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

_LENGTH_ATOL_M = 1e-9
_BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"
_UNIT_LINES = (
    LineString([(0.05, 0.93), (0.31, 0.62), (0.47, 0.55), (0.66, 0.31), (0.97, 0.08)]),
    LineString([(0.12, 0.1), (0.4, 0.42), (0.41, 0.8), (0.9, 0.86)]),
)


def _regular() -> PlanarCellMesh:
    mesh = solver_mesh_from_structured_arrays(
        nrow=30,
        ncol=40,
        top=np.zeros((30, 40)),
        botm=np.full((1, 30, 40), -10.0),
        dx=37.3,
        dy=41.7,
        xoff=350_000.37,
        yoff=6_780_000.11,
    )
    return mesh.cell_mesh


def _meshes() -> dict[str, PlanarCellMesh]:
    return {
        "regular": _regular(),
        "triangles": bundle_triangles(_BUNDLE)[0],
        "dual": bundle_dual(_BUNDLE)[0],
    }


def _lines_on(cell_mesh: PlanarCellMesh) -> list[LineString]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(line, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for line in _UNIT_LINES
    ]


def _gridintersect_reach(cell_mesh: PlanarCellMesh, line: LineString) -> list[tuple[int, float]]:
    """The split of the former builder: GridIntersect pieces ordered along the line."""
    n_cells = cell_mesh.n_cells
    disv = to_flopy_disv_args(cell_mesh.mesh, top=np.zeros(n_cells), botm=np.full((1, n_cells), -1))
    grid = VertexGrid(
        vertices=disv["vertices"],
        cell2d=disv["cell2d"],
        top=np.zeros(n_cells),
        botm=np.full((1, n_cells), -1.0),
        nlay=1,
        ncpl=n_cells,
        xoff=0.0,
        yoff=0.0,
    )
    pieces = []
    for row in GridIntersect(grid).intersect(line, geo_dataframe=False):
        length = float(row["lengths"])
        if length < 1e-6:
            continue
        middle = row["ixshapes"].interpolate(0.5, normalized=True)
        pieces.append((float(line.project(middle)), int(row["cellids"]), length))
    pieces.sort()
    return [(cell, length) for _, cell, length in pieces]


@pytest.mark.parametrize("name", ["regular", "triangles", "dual"])
def test_the_reach_pieces_are_those_of_gridintersect(name: str) -> None:
    cell_mesh = _meshes()[name]
    for line in _lines_on(cell_mesh):
        expected = _gridintersect_reach(cell_mesh, line)
        pieces = crossing_pieces(cell_mesh, line)
        assert [piece.cell for piece in pieces] == [cell for cell, _ in expected]
        np.testing.assert_allclose(
            [piece.length for piece in pieces],
            [length for _, length in expected],
            rtol=0.0,
            atol=_LENGTH_ATOL_M,
        )
        assert sum(piece.length for piece in pieces) == pytest.approx(line.length, rel=1e-12)
