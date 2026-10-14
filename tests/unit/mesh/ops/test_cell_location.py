"""``locate_cells`` equals the reader it replaces on a grid and a brute-force search elsewhere.

On a regular grid the oracle is the floor arithmetic of the well builder. On an unstructured
mesh it is the cell of smallest id that covers the point. The probes include points on edges
and on vertices.
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import box

from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells
from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual, bundle_triangles

WKT = CRS.from_epsg(2154).to_wkt()
NROW, NCOL, SIZE = 7, 5, 12.3
XMIN, YMIN = 1000.25, 2000.5
N_RANDOM = 200
N_EDGE_PROBES = 40


def _grid(xmin: float, ymin: float, size: float) -> PlanarCellMesh:
    xmax, ymax = xmin + NCOL * size, ymin + NROW * size
    request = MeshRequest(
        domain=box(xmin, ymin, xmax, ymax),
        crs_wkt=WKT,
        grid=RasterGridSpec(
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            dx=size,
            dy=size,
            nrow=NROW,
            ncol=NCOL,
            crs_wkt=WKT,
        ),
        nominal_size_m=size,
    )
    return RegularMeshEngine().build(request)


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
