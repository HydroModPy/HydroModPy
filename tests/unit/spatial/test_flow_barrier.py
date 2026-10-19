"""Map a barrier line onto the mesh faces it separates (a continuous cut).

A cutoff wall is barred on the shared faces whose two cells the trace passes
BETWEEN (the segment joining their centres is crossed), so the barrier is a
single connected fence with no leak paths, independent of the grid. The centres
are those of the cell mesh.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.ops.flow_barrier import (
    barrier_faces_from_line,
    cutoff_wall_faces,
    downstream_of_wall,
    lake_shore_faces,
    wall_leaks,
)
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of


def _quad_grid(nx: int, ny: int) -> HydroMesh:
    """An ``nx`` by ``ny`` grid of unit quads; cell (i, j) has id ``j * nx + i``."""
    verts = np.array([[i, j] for j in range(ny + 1) for i in range(nx + 1)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * (nx + 1) + i

    conn = np.array(
        [
            [v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)]
            for j in range(ny)
            for i in range(nx)
        ],
        dtype=int,
    )
    return HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))


def _n_components(faces, mesh: HydroMesh) -> int:
    """Connected components of the graph formed by the barred faces' shared edges."""
    conn = mesh.flat_connectivity

    def edges(ci: int) -> set[tuple[int, int]]:
        cell = [int(k) for k in conn[ci]]
        return {tuple(sorted((cell[k], cell[(k + 1) % len(cell)]))) for k in range(len(cell))}

    barred: set[tuple[int, int]] = set()
    for f in faces:
        barred |= edges(f.cell_a) & edges(f.cell_b)
    adj: dict[int, set[int]] = {}
    for a, b in barred:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen: set[int] = set()
    comps = 0
    for start in adj:
        if start in seen:
            continue
        comps += 1
        stack = [start]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(adj[u])
    return comps


def test_cutting_line_bars_a_connected_chain_of_faces() -> None:
    # A near-vertical trace across a 2x3 grid separates the left column from the
    # right one at every row: the barred faces are a single connected fence.
    mesh = _quad_grid(2, 3)
    faces = barrier_faces_from_line(cell_mesh_of(mesh), LineString([(1.01, -0.5), (1.01, 3.5)]))
    assert {(f.cell_a, f.cell_b) for f in faces} == {(0, 1), (2, 3), (4, 5)}
    assert _n_components(faces, mesh) == 1


def test_only_faces_the_trace_separates_are_barred() -> None:
    # A near-horizontal trace between row 0 and row 1 bars exactly those two faces.
    mesh = _quad_grid(2, 3)
    faces = barrier_faces_from_line(cell_mesh_of(mesh), LineString([(-0.5, 1.01), (2.5, 1.01)]))
    assert {(f.cell_a, f.cell_b) for f in faces} == {(0, 2), (1, 3)}
    assert _n_components(faces, mesh) == 1


def test_faces_are_ordered_along_the_line() -> None:
    mesh = _quad_grid(2, 3)
    faces = barrier_faces_from_line(cell_mesh_of(mesh), LineString([(1.01, -0.5), (1.01, 3.5)]))
    stations = [f.s for f in faces]
    assert stations == sorted(stations)
    assert all(0.0 <= s <= 1.0 for s in stations)


def test_line_inside_one_cell_bars_nothing() -> None:
    mesh = _quad_grid(2, 3)
    assert barrier_faces_from_line(cell_mesh_of(mesh), LineString([(0.2, 0.2), (0.8, 0.8)])) == []


def _two_cells_centred_on(centres: list[tuple[float, float]]) -> PlanarCellMesh:
    """Two unit quads side by side, sharing the face x = 1, with the given centres."""
    mesh = _quad_grid(2, 1)
    return build_planar_cell_mesh(
        mesh,
        np.asarray(centres, dtype=float),
        center_kind="generator",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
    )


def test_the_barrier_reads_the_centres_of_the_cell_mesh() -> None:
    # The trace x = 1.3 runs inside the east cell. With the vertex means as centres
    # it separates them; with the east centre at x = 1.2 it does not.
    line = LineString([(1.3, -0.5), (1.3, 1.5)])
    vertex_means = _two_cells_centred_on([(0.5, 0.5), (1.5, 0.5)])
    shifted = _two_cells_centred_on([(0.5, 0.5), (1.2, 0.5)])
    assert [(f.cell_a, f.cell_b) for f in barrier_faces_from_line(vertex_means, line)] == [(0, 1)]
    assert barrier_faces_from_line(shifted, line) == []


# A 6 x 6 grid with the lake on the 2 x 6 strip of its two western columns. The wall
# runs north along x = 2, lake on its left, across the whole grid.
_LAKE = [j * 6 + i for j in range(6) for i in range(2)]
_WALL = LineString([(2.0, 0.0), (2.0, 6.0)])


def test_a_point_round_the_end_of_the_wall_is_not_downstream() -> None:
    points = np.array([[2.5, 3.0], [1.5, 3.0], [2.5, 7.0], [2.0, 3.0]])
    assert downstream_of_wall(_WALL, points).tolist() == [True, False, False, False]


def test_the_shore_faces_are_the_lake_faces_across_the_wall() -> None:
    cell_mesh = cell_mesh_of(_quad_grid(6, 6))
    rows = lake_shore_faces(cell_mesh, _WALL, np.array(_LAKE))
    pairs = {tuple(pair) for pair in cell_mesh.geometry.edge_cells[rows].tolist()}
    assert pairs == {(j * 6 + 1, j * 6 + 2) for j in range(6)}


def test_a_wall_missing_a_face_leaks_and_a_whole_wall_does_not() -> None:
    cell_mesh = cell_mesh_of(_quad_grid(6, 6))
    lake = np.array(_LAKE)
    faces = cutoff_wall_faces(cell_mesh, _WALL, lake)
    assert len(faces) == 6
    assert wall_leaks(cell_mesh, _WALL, lake, faces, reach=3.0).size == 0
    assert wall_leaks(cell_mesh, _WALL, lake, faces[1:], reach=3.0).size > 0
