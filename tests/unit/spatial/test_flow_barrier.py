"""Map a barrier line onto the mesh faces it separates (a continuous cut).

A cutoff wall is barred on the shared faces whose two cells the trace passes
BETWEEN (its centroid-segment is crossed), so the barrier is a single connected
fence with no leak paths, independent of the grid.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.flow_barrier import barrier_faces_from_line


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
    faces = barrier_faces_from_line(mesh, LineString([(1.01, -0.5), (1.01, 3.5)]))
    assert {(f.cell_a, f.cell_b) for f in faces} == {(0, 1), (2, 3), (4, 5)}
    assert _n_components(faces, mesh) == 1


def test_only_faces_the_trace_separates_are_barred() -> None:
    # A near-horizontal trace between row 0 and row 1 bars exactly those two faces.
    mesh = _quad_grid(2, 3)
    faces = barrier_faces_from_line(mesh, LineString([(-0.5, 1.01), (2.5, 1.01)]))
    assert {(f.cell_a, f.cell_b) for f in faces} == {(0, 2), (1, 3)}
    assert _n_components(faces, mesh) == 1


def test_faces_are_ordered_along_the_line() -> None:
    mesh = _quad_grid(2, 3)
    faces = barrier_faces_from_line(mesh, LineString([(1.01, -0.5), (1.01, 3.5)]))
    stations = [f.s for f in faces]
    assert stations == sorted(stations)
    assert all(0.0 <= s <= 1.0 for s in stations)


def test_line_inside_one_cell_bars_nothing() -> None:
    mesh = _quad_grid(2, 3)
    assert barrier_faces_from_line(mesh, LineString([(0.2, 0.2), (0.8, 0.8)])) == []
