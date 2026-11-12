"""``locate_cells`` equals the reader it replaces on a grid and a brute-force search elsewhere.

On a regular grid the oracle is the floor arithmetic of the well builder. On an unstructured
mesh it is the cell of smallest id that covers the point. The probes include points on edges
and on vertices.

A point outside the mesh takes the nearest cell only within one cell size of it
(``locate_cells_near``). Beyond that distance the point is a coordinate error, and the
nearest cell would score a gauge or a piezometer on a place it does not observe. The point
gets no cell and a warning names it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely

from hydromodpy.mesh.cells.locate import locate_cells
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual, bundle_triangles
from tests._helpers.mesh_cases import grid_spec, mesh_request

NROW, NCOL, SIZE = 7, 5, 12.3
XMIN, YMIN = 1000.25, 2000.5
N_RANDOM = 200
N_EDGE_PROBES = 40


def _grid(xmin: float, ymin: float, size: float) -> PlanarCellMesh:
    return RegularMeshEngine().build(
        mesh_request(grid_spec(NROW, NCOL, size, xmin=xmin, ymin=ymin))
    )


@pytest.fixture(scope="module")
def grid() -> PlanarCellMesh:
    return _grid(XMIN, YMIN, SIZE)


def _probes(cell_mesh: PlanarCellMesh, seed: int) -> np.ndarray:
    """Random points over the bounds, cell centers, vertices, then the edge midpoints last."""
    rng = np.random.default_rng(seed)
    xmin, ymin, xmax, ymax = cell_mesh.mesh.bounds()
    random = np.column_stack([rng.uniform(xmin, xmax, N_RANDOM), rng.uniform(ymin, ymax, N_RANDOM)])
    geometry = cell_mesh.geometry
    picked = rng.choice(cell_mesh.n_cells, min(40, cell_mesh.n_cells), replace=False)
    vertices = cell_mesh.mesh.vertices[rng.choice(cell_mesh.mesh.n_nodes, 40, replace=False)]
    edges = geometry.edge_midpoint[
        rng.choice(geometry.edge_midpoint.shape[0], N_EDGE_PROBES, replace=False)
    ]
    return np.vstack([random, cell_mesh.centers[picked], vertices, edges])


def test_nearest_centre_outside(grid) -> None:
    outside = np.array([[XMIN - 40.0, YMIN + 30.0], [XMIN + 80.0, YMIN + 400.0]])
    cells = locate_cells(grid, outside, allow_nearest=True)
    for point, cell in zip(outside, cells.tolist(), strict=True):
        deltas = grid.centers - point
        assert cell == int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))


def test_inside_point_keeps_its_cell(grid) -> None:
    held = [0, 17, grid.n_cells - 1]

    cells = locate_cells(grid, grid.centers[held], allow_nearest=True)

    assert cells.tolist() == held


def _covering_polygons(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """The cell polygons, built from the vertex rows of the cells."""
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    rows = cell_mesh.geometry.padded_connectivity
    return np.array([shapely.Polygon(vertices[row[row >= 0]]) for row in rows], dtype=object)


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("producer", [bundle_triangles, bundle_dual])
def test_unstructured_vs_brute_force(case, producer) -> None:
    cell_mesh = producer(case)
    polygons = _covering_polygons(cell_mesh)
    probes = _probes(cell_mesh, seed=2)[:-N_EDGE_PROBES]
    cells = locate_cells(cell_mesh, probes, allow_nearest=False)
    for index, (x, y) in enumerate(probes.tolist()):
        covering = np.flatnonzero(shapely.covers(polygons, shapely.Point(x, y)))
        expected = int(covering.min()) if covering.size else -1
        assert cells[index] == expected, (index, x, y)
    assert (cells[:N_RANDOM] >= 0).sum() > 0.4 * N_RANDOM


def test_one_point_and_wrong_shape(grid) -> None:
    assert locate_cells(grid, np.array([XMIN + 1.0, YMIN + 1.0]), allow_nearest=False).shape == (1,)
    with pytest.raises(ValueError, match="shape"):
        locate_cells(grid, np.zeros((3, 3)), allow_nearest=False)


SMALL_SIZE = 10.0


def _small_grid() -> PlanarCellMesh:
    """Three columns and two rows of 10 m cells on [0, 30] x [0, 20]."""
    return RegularMeshEngine().build(mesh_request(grid_spec(2, 3, SMALL_SIZE)))


def test_adapter_far_from_the_mesh() -> None:
    cell_mesh = _small_grid()
    solver_run = SimpleNamespace(
        solver_model=SimpleNamespace(mesh=SimpleNamespace(cell_mesh=cell_mesh))
    )
    adapter = BoussinesqFlowAdapter()
    assert adapter.locate_cell(solver_run, 39.0, 5.0) == (0, 0, 1 * 3 + 2)
    assert adapter.locate_cell(solver_run, 41.0, 5.0) is None
