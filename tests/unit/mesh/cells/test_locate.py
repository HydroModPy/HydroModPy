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

from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.spatial.mesh.cells.locate import locate_cells, locate_cells_near
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
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


def _wells_arithmetic(grid: PlanarCellMesh, x: float, y: float) -> int:
    """The coordinate branch of ``resolve_well_disv_cell`` on a structured grid; -1 outside."""
    nrow, ncol = grid.structured_shape
    xmin, ymin, xmax, ymax = grid.mesh.bounds()
    dx = (xmax - xmin) / ncol
    dy = (ymax - ymin) / nrow
    if x < xmin or x > xmax or y < ymin or y > ymax:
        return -1
    col = int((x - xmin) / dx)
    row = int((ymax - y) / dy)
    if col == ncol and x == xmax:
        col = ncol - 1
    if row == nrow and y == ymin:
        row = nrow - 1
    return row * ncol + col


def _probes(cell_mesh: PlanarCellMesh, seed: int) -> np.ndarray:
    """Random points over the bounds, cell centres, vertices, then the edge midpoints last."""
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


def test_a_grid_is_located_like_the_well_arithmetic(grid) -> None:
    probes = _probes(grid, seed=1)
    corners = np.array(
        [
            [XMIN, YMIN],
            [XMIN, YMIN + NROW * SIZE],
            [XMIN + NCOL * SIZE, YMIN],
            [XMIN + NCOL * SIZE, YMIN + NROW * SIZE],
        ]
    )
    outside = np.array([[XMIN - 1.0, YMIN + 3.0], [XMIN + 3.0, YMIN + NROW * SIZE + 0.1]])
    points = np.vstack([probes, corners, outside])
    expected = [_wells_arithmetic(grid, x, y) for x, y in points]
    assert locate_cells(grid, points, allow_nearest=False).tolist() == expected
    assert expected[-1] == -1 and expected[-2] == -1


def test_a_grid_point_on_an_edge_belongs_to_the_cell_east_or_south() -> None:
    exact = _grid(1000.0, 2000.0, 10.0)
    on_edge = np.array([[1020.0, 2055.0], [1015.0, 2030.0], [1050.0, 2070.0], [1000.0, 2000.0]])
    cells = locate_cells(exact, on_edge, allow_nearest=False)
    assert cells.tolist() == [1 * NCOL + 2, 4 * NCOL + 1, 0 * NCOL + NCOL - 1, (NROW - 1) * NCOL]


def test_a_point_outside_a_grid_takes_the_nearest_centre_when_allowed(grid) -> None:
    outside = np.array([[XMIN - 40.0, YMIN + 30.0], [XMIN + 80.0, YMIN + 400.0]])
    cells = locate_cells(grid, outside, allow_nearest=True)
    for point, cell in zip(outside, cells.tolist(), strict=True):
        deltas = grid.centers - point
        assert cell == int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))


def test_a_point_inside_a_cell_keeps_it_when_the_nearest_is_allowed(grid) -> None:
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
def test_an_unstructured_mesh_is_located_like_a_brute_force_search(case, producer) -> None:
    cell_mesh = producer(case)
    polygons = _covering_polygons(cell_mesh)
    probes = _probes(cell_mesh, seed=2)[:-N_EDGE_PROBES]
    cells = locate_cells(cell_mesh, probes, allow_nearest=False)
    for index, (x, y) in enumerate(probes.tolist()):
        covering = np.flatnonzero(shapely.covers(polygons, shapely.Point(x, y)))
        expected = int(covering.min()) if covering.size else -1
        assert cells[index] == expected, (index, x, y)
    assert (cells[:N_RANDOM] >= 0).sum() > 0.4 * N_RANDOM


@pytest.mark.parametrize("producer", [bundle_triangles, bundle_dual])
def test_an_edge_midpoint_is_in_one_of_the_two_cells_of_the_edge(producer) -> None:
    cell_mesh = producer(BUNDLE_CASES[2])
    geometry = cell_mesh.geometry
    inner = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)[:60]
    cells = locate_cells(cell_mesh, geometry.edge_midpoint[inner], allow_nearest=False)
    for edge, cell in zip(inner.tolist(), cells.tolist(), strict=True):
        assert cell in geometry.edge_cells[edge].tolist()


def test_a_shared_vertex_gives_the_smallest_cell_id() -> None:
    cell_mesh = bundle_triangles(BUNDLE_CASES[2])
    padded = cell_mesh.geometry.padded_connectivity
    nodes = padded[:, 0]
    for node in nodes[:30].tolist():
        incident = np.flatnonzero((padded == node).any(axis=1))
        found = locate_cells(cell_mesh, cell_mesh.mesh.vertices[[node]], allow_nearest=False)
        assert found[0] == incident.min()


def test_an_unstructured_point_outside_is_lost_or_snapped_to_the_nearest_centre() -> None:
    cell_mesh = bundle_triangles(BUNDLE_CASES[2])
    xmin, ymin, xmax, ymax = cell_mesh.mesh.bounds()
    outside = np.array([[xmin - 50.0, ymin - 50.0], [xmax + 20.0, (ymin + ymax) / 2]])
    assert locate_cells(cell_mesh, outside, allow_nearest=False).tolist() == [-1, -1]
    snapped = locate_cells(cell_mesh, outside, allow_nearest=True)
    for point, cell in zip(outside, snapped.tolist(), strict=True):
        deltas = cell_mesh.centers - point
        assert cell == int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))


def test_one_point_and_a_wrong_shape(grid) -> None:
    assert locate_cells(grid, np.array([XMIN + 1.0, YMIN + 1.0]), allow_nearest=False).shape == (1,)
    with pytest.raises(ValueError, match="shape"):
        locate_cells(grid, np.zeros((3, 3)), allow_nearest=False)


SMALL_SIZE = 10.0


def _small_grid() -> PlanarCellMesh:
    """Three columns and two rows of 10 m cells on [0, 30] x [0, 20]."""
    return RegularMeshEngine().build(mesh_request(grid_spec(2, 3, SMALL_SIZE)))


def test_a_point_inside_the_mesh_gets_the_cell_that_holds_it() -> None:
    grid = _small_grid()
    points = np.array([[5.0, 15.0], [25.0, 5.0], [15.0, 10.0]])
    np.testing.assert_array_equal(
        locate_cells_near(grid, points), locate_cells(grid, points, allow_nearest=False)
    )


def test_a_point_within_a_cell_size_takes_the_nearest_cell() -> None:
    # 9 m east of the east side, beside the south-east cell (row 1, column 2).
    assert locate_cells_near(_small_grid(), np.array([[39.0, 5.0]])).tolist() == [1 * 3 + 2]


def test_a_point_farther_than_a_cell_size_is_lost_and_named(caplog) -> None:
    with caplog.at_level("WARNING"):
        cells = locate_cells_near(_small_grid(), np.array([[41.0, 5.0], [39.0, 5.0]]))
    assert cells.tolist() == [-1, 1 * 3 + 2]
    assert "(41.00, 5.00)" in caplog.text
    assert "(39.00, 5.00)" not in caplog.text


def test_the_bound_is_the_size_of_the_nearest_cell_on_triangles() -> None:
    cell_mesh = bundle_triangles(BUNDLE_CASES[2])
    xmin, ymin, xmax, ymax = cell_mesh.mesh.bounds()
    probe = np.array([[xmax + 1.0e4, 0.5 * (ymin + ymax)]])
    assert locate_cells_near(cell_mesh, probe).tolist() == [-1]
    centre = cell_mesh.centers[[0]]
    assert locate_cells_near(cell_mesh, centre).tolist() == [0]


def test_the_boussinesq_adapter_locates_no_cell_far_from_its_mesh() -> None:
    cell_mesh = _small_grid()
    ctx = SimpleNamespace(model=SimpleNamespace(mesh=SimpleNamespace(cell_mesh=cell_mesh)))
    adapter = BoussinesqFlowAdapter()
    assert adapter.locate_cell(ctx, 39.0, 5.0) == (0, 0, 1 * 3 + 2)
    assert adapter.locate_cell(ctx, 41.0, 5.0) is None
