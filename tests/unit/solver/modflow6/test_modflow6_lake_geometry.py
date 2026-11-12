"""Lake geometry on a cell mesh: overlap areas (m2), arm cells and cutoff-wall faces.

A lake owns its closed regions and the cells outside them that it covers for most
of their area. A cutoff wall runs with the lake on its left. Its shore faces join a
lake cell to a cell across the wall, and a wall that misses one of them leaks.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _drop_interior_rings,
    cutoff_wall_faces,
    downstream_of_wall,
    interior_cells,
    lake_shore_faces,
    polygon_overlap,
    wall_leaks,
)
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh, voronoi_lake_mesh

X0, Y0 = L93_ORIGIN

BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)
ARM = box(X0 + 700.0, Y0 + 430.0, X0 + 950.0, Y0 + 470.0)

# A 6 x 6 grid with the lake on the 2 x 6 strip of its two western columns. The wall
# runs north along x = 2, lake on its left, across the whole grid.
LAKE_CELLS = np.array([j * 6 + i for j in range(6) for i in range(2)])
WALL = LineString([(2.0, 0.0), (2.0, 6.0)])


def mesh_on_the_body_ring():
    """The Voronoi mesh of a 1.2 x 0.9 km domain whose faces follow the body of the lake."""
    return voronoi_lake_mesh(
        shapely.normalize(BODY),
        domain=box(X0, Y0, X0 + 1200.0, Y0 + 900.0),
        pixel=10.0,
        cell_size=30.0,
    )


def test_arm_cells_covered_for_most_of_their_area_join_the_lake() -> None:
    mesh = mesh_on_the_body_ring()
    lake = BODY.union(ARM)

    cells = interior_cells(mesh, "lakes", lake)

    overlap_cells, overlap = polygon_overlap(mesh, lake)
    share = np.zeros(mesh.n_cells)
    share[overlap_cells] = overlap / mesh.geometry.areas[overlap_cells]
    in_arm = shapely.contains(ARM.buffer(1.0), shapely.points(mesh.centers))
    assert mesh.qa.families["lakes"]["covered_length_rel"] > 1.0 - 1e-6
    assert np.any(in_arm & (share > 0.5))
    assert set(np.flatnonzero(in_arm & (share > 0.5)).tolist()) <= set(cells.tolist())
    outside_body = cells[~shapely.contains(BODY, shapely.points(mesh.centers[cells]))]
    assert np.all(share[outside_body] > 0.5)


def test_a_lake_off_every_region_owns_nothing() -> None:
    assert interior_cells(mesh_on_the_body_ring(), "lakes", ARM).size == 0


def test_a_box_overlaps_the_cells_by_the_area_it_covers() -> None:
    grid = regular_mesh(3, 4, dx=10.0)

    cells, overlap = polygon_overlap(grid, box(0.0, 0.0, 15.0, 30.0))

    assert cells.tolist() == [0, 1, 4, 5, 8, 9]
    np.testing.assert_allclose(overlap, [100.0, 50.0] * 3)


def test_a_point_round_the_end_of_the_wall_is_not_downstream() -> None:
    points = np.array([[2.5, 3.0], [1.5, 3.0], [2.5, 7.0], [2.0, 3.0]])

    assert downstream_of_wall(WALL, points).tolist() == [True, False, False, False]


def test_shore_faces_are_the_lake_faces_across_the_wall() -> None:
    cell_mesh = regular_mesh(6, 6)

    rows = lake_shore_faces(cell_mesh, WALL, LAKE_CELLS)

    pairs = {tuple(pair) for pair in cell_mesh.geometry.edge_cells[rows].tolist()}
    assert pairs == {(j * 6 + 1, j * 6 + 2) for j in range(6)}


def test_a_wall_missing_a_face_leaks() -> None:
    cell_mesh = regular_mesh(6, 6)

    faces = cutoff_wall_faces(cell_mesh, WALL, LAKE_CELLS)

    assert len(faces) == 6
    assert wall_leaks(cell_mesh, WALL, LAKE_CELLS, faces, reach=3.0).size == 0
    assert wall_leaks(cell_mesh, WALL, LAKE_CELLS, faces[1:], reach=3.0).size > 0


def test_a_wall_away_from_the_lake_bars_nothing() -> None:
    far = LineString([(20.0, 0.0), (20.0, 6.0)])

    assert cutoff_wall_faces(regular_mesh(6, 6), far, LAKE_CELLS) == []


def test_drop_interior_rings() -> None:
    ring = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)]
    solid = Polygon(ring)
    holed = Polygon(ring, holes=[[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]])

    filled = _drop_interior_rings(holed)

    assert len(holed.interiors) == 1
    assert len(filled.interiors) == 0
    assert filled.covers(Point(1.5, 1.5))
    assert _drop_interior_rings(solid) is solid
