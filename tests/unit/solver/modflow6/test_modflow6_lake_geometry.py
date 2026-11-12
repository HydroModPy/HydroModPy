"""Lake geometry on a cell mesh: overlap areas (m2), arm cells and cutoff-wall faces.

A lake owns its closed regions and the cells outside them that it covers for most
of their area. A cutoff wall runs with the lake on its left. Its shore faces join a
lake cell to a cell across the wall, and a wall that misses one of them leaks.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _abacus_stage_sarea,
    _abacus_volume,
    _drop_cutoff_wall_downstream_cells,
    _drop_interior_rings,
    _first_active_layer_below,
    _point_to_segment_distance,
    cutoff_wall_faces,
    downstream_of_wall,
    interior_cells,
    lake_shore_faces,
    polygon_overlap,
    wall_leaks,
)
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh, voronoi_lake_mesh
from tests._helpers.model_factory import make_model

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


def test_drop_interior_rings_of_a_multipolygon() -> None:
    ring = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)]
    hole = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]
    far = [(10.0, 0.0), (13.0, 0.0), (13.0, 3.0), (10.0, 3.0)]
    two_islands = MultiPolygon([Polygon(ring, holes=[hole]), Polygon(far, holes=[hole])])

    filled = _drop_interior_rings(two_islands)

    assert [len(part.interiors) for part in filled.geoms] == [0, 0]
    assert filled.area == pytest.approx(18.0)  # 2 parts x 3 m x 3 m
    point = Point(1.0, 1.0)
    assert _drop_interior_rings(point) is point


ABACUS_COLUMNS = {"stage": [1.0, 2.0], "volume": [0.0, 5.0], "sarea": [3.0, 4.0]}

VOLUME_COLUMNS = [
    pytest.param(None, None, id="no abacus"),
    pytest.param({"stage": [1.0]}, None, id="mapping without volume"),
    pytest.param(SimpleNamespace(volume=None), None, id="object without volume"),
    pytest.param(ABACUS_COLUMNS, [0.0, 5.0], id="mapping"),
    pytest.param(SimpleNamespace(volume=(0, 5)), [0.0, 5.0], id="object"),
]


@pytest.mark.parametrize(("abacus", "volume"), VOLUME_COLUMNS)
def test_volume_column_of_an_abacus(abacus, volume) -> None:
    assert _abacus_volume(abacus) == volume


STAGE_SAREA_COLUMNS = [
    pytest.param(None, (None, None), id="no abacus"),
    pytest.param({"stage": [1.0, 2.0]}, (None, None), id="mapping without sarea"),
    pytest.param(SimpleNamespace(stage=[1.0]), (None, None), id="object without sarea"),
    pytest.param(ABACUS_COLUMNS, ([1.0, 2.0], [3.0, 4.0]), id="mapping"),
    pytest.param(
        SimpleNamespace(stage=(1, 2), sarea=(3, 4)), ([1.0, 2.0], [3.0, 4.0]), id="object"
    ),
]


@pytest.mark.parametrize(("abacus", "columns"), STAGE_SAREA_COLUMNS)
def test_stage_and_sarea_columns_of_an_abacus(abacus, columns) -> None:
    assert _abacus_stage_sarea(abacus) == columns


def test_distance_to_a_segment_reduced_to_a_point() -> None:
    corner = np.array([0.0, 0.0])

    # 3-4-5 triangle between the point and the degenerate segment
    assert _point_to_segment_distance(np.array([3.0, 4.0]), corner, corner) == pytest.approx(5.0)


def test_no_active_layer_below_the_lake_cap() -> None:
    # Layer 0 is the cap, layers 1 and 2 are pass-through (-1) and inactive (0) in cell 1.
    idomain = np.array([[1, 1], [1, -1], [1, 0]])

    assert _first_active_layer_below(idomain, 0, occupied_layers=1, nlay=3) == 1
    assert _first_active_layer_below(idomain, 1, occupied_layers=1, nlay=3) is None


def lake_behind_a_wall(cells: list[int]):
    """A 6 x 6 grid, a wall along x = 2 with the lake on its west, and a lake over ``cells``."""
    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={"res": {"cutoff_wall_line": WALL}},
        )
    )
    solver_mesh = SimpleNamespace(cell_mesh=regular_mesh(6, 6))
    cells_by_lake = {"res": list(cells)}
    areas = {"res": {cell: 1.0 for cell in cells}}
    return model, cells_by_lake, areas, solver_mesh


def test_lake_cells_behind_the_wall_are_dropped(caplog) -> None:
    # Columns 0 to 3 of every row. Columns 2 and 3 are east of the wall, so downstream.
    cells = [j * 6 + i for j in range(6) for i in range(4)]
    model, cells_by_lake, areas, solver_mesh = lake_behind_a_wall(cells)

    _drop_cutoff_wall_downstream_cells(model, cells_by_lake, areas, solver_mesh)

    assert cells_by_lake["res"] == LAKE_CELLS.tolist()
    assert sorted(areas["res"]) == LAKE_CELLS.tolist()
    assert "dropped 12 LAK cell(s)" in caplog.text


def test_a_lake_wholly_behind_the_wall_is_refused() -> None:
    cells = [j * 6 + i for j in range(6) for i in (3, 4)]
    model, cells_by_lake, areas, solver_mesh = lake_behind_a_wall(cells)

    with pytest.raises(ValueError, match="check the trace orientation"):
        _drop_cutoff_wall_downstream_cells(model, cells_by_lake, areas, solver_mesh)
