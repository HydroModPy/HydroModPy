"""On a mesh whose faces do not follow the shore, a lake owns the cells flopy's GridIntersect gave.

The LAK builder resolved a lake polygon with ``flopy.utils.GridIntersect`` on a
``VertexGrid`` rebuilt from the mesh, then recomputed each overlap area with
shapely. It now reads the cell mesh: the cells the polygon overlaps by a
positive area, with that area. The two are compared on a regular grid at a
non-integer origin, on the triangles and on the Voronoi dual of a committed
bundle: same cells, areas within 1e-9.
"""

from __future__ import annotations

import numpy as np
import pytest
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders.lake import resolve_lake_cells
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

_AREA_RTOL = 1e-9
_BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"
_UNIT_LAKES = (
    Polygon([(0.2, 0.25), (0.55, 0.18), (0.71, 0.47), (0.48, 0.69), (0.23, 0.58)]),
    Polygon(
        [(0.6, 0.6), (0.92, 0.62), (0.88, 0.9), (0.62, 0.86)],
        holes=[[(0.7, 0.7), (0.8, 0.71), (0.78, 0.8), (0.71, 0.79)]],
    ),
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
        "triangles": bundle_triangles(_BUNDLE),
        "dual": bundle_dual(_BUNDLE),
    }


def _lakes_on(cell_mesh: PlanarCellMesh) -> list[Polygon]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(lake, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for lake in _UNIT_LAKES
    ]


def _gridintersect_lake(cell_mesh: PlanarCellMesh, polygon: Polygon) -> dict[int, float]:
    """The rule of the former builder: GridIntersect cells, overlap recomputed by shapely."""
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
    result = GridIntersect(grid).intersect(polygon, geo_dataframe=False)
    verts = np.asarray(grid.verts)
    areas = {}
    for cell in sorted({int(c) for c in np.asarray(result["cellids"]).ravel()}):
        ring = verts[[int(i) for i in grid.cell2d[cell][4:] if int(i) >= 0]][:, :2]
        areas[cell] = float(Polygon(ring).intersection(polygon).area)
    return areas


@pytest.mark.parametrize("name", ["regular", "triangles", "dual"])
def test_the_lake_cells_and_areas_are_those_of_gridintersect(name: str) -> None:
    cell_mesh = _meshes()[name]
    for index, lake in enumerate(_lakes_on(cell_mesh)):
        expected = _gridintersect_lake(cell_mesh, lake)
        cells, areas = resolve_lake_cells(
            None, lake_id=f"lake{index}", polygon=lake, cell_mesh=cell_mesh, with_areas=True
        )
        assert cells == sorted(expected)
        got = np.array([areas[c] for c in cells])
        want = np.array([expected[c] for c in cells])
        np.testing.assert_allclose(got, want, rtol=_AREA_RTOL, atol=_AREA_RTOL * lake.area)
        assert sum(areas.values()) == pytest.approx(lake.area, rel=_AREA_RTOL)
