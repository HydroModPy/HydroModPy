"""The solver adapter of D: inactive lakes are crossed, CHD cells seed, the top stays.

A fixed-area lake is inactive in every layer of the solver, yet water crosses
it: its cells must be on the descended graph. Lakes are numbered in the order
build.py numbers LAK lakes in, the iteration order of the mapping.
"""

from __future__ import annotations

import logging

import numpy as np

from hydromodpy.solver.modflow_common.mesh_descent import build_solver_mesh_descent
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from tests._helpers.ugrid_meshes import quad_mesh

N = 7


def _cell(row: int, col: int) -> int:
    return row * N + col


def _grid_mesh(inactive_mask: np.ndarray) -> SolverMesh:
    vertices, connectivity = quad_mesh(N, N)
    rows, cols = np.divmod(np.arange(N * N), N)
    return SolverMesh(
        planar_mesh=HydroMesh(
            vertices=vertices[:, :2],
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        ),
        top=20.0 + rows + cols,
        botm=np.stack([np.zeros(N * N), np.full(N * N, -10.0)]),
        inactive_mask=inactive_mask,
    )


def test_an_inactive_lake_is_on_the_graph_and_numbered_in_order() -> None:
    inactive = np.zeros((2, N * N), dtype=bool)
    west_lake = [_cell(3, 1), _cell(3, 2)]
    east_lake = [_cell(3, 4), _cell(3, 5)]
    inactive[:, west_lake + east_lake] = True
    off_domain = _cell(5, 5)
    inactive[:, off_domain] = True
    deeper_only = _cell(1, 3)
    inactive[0, deeper_only] = True
    mesh = _grid_mesh(inactive)
    top_before = mesh.top.copy()

    descent = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={"east": east_lake, "west": west_lake},
        base_level_mask=None,
    )

    assert np.all(descent.routable[west_lake + east_lake])
    assert descent.routable[deeper_only]
    assert not descent.routable[off_domain]
    assert descent.lake_of[east_lake].tolist() == [0, 0]
    assert descent.lake_of[west_lake].tolist() == [1, 1]
    assert np.array_equal(mesh.top, top_before)


def test_a_constant_head_cell_seeds_the_descent(caplog) -> None:
    mesh = _grid_mesh(np.zeros((2, N * N), dtype=bool))
    pit = _cell(3, 3)
    top = mesh.top.copy()
    top[pit] = 0.0
    mesh = SolverMesh(
        planar_mesh=mesh.planar_mesh, top=top, botm=mesh.botm, inactive_mask=mesh.inactive_mask
    )
    base_level = np.zeros(N * N, dtype=bool)
    base_level[pit] = True

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)

    assert descent.base_level[pit]
    assert descent.n_raised == 0
    assert "shared nodes (D8)" in caplog.text


def test_a_ragged_polygon_mesh_descends_by_shared_faces() -> None:
    # One quad and two triangles: the first triangle meets the quad at a node only.
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]])
    cells = ([0, 1, 4, 3], [1, 2, 5], [1, 5, 4])
    mesh = SolverMesh(
        planar_mesh=HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),)),
        top=np.array([3.0, 1.0, 2.0]),
        botm=np.zeros((1, 3)),
        inactive_mask=np.zeros((1, 3), dtype=bool),
    )

    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)

    assert not descent.diagonal_neighbors
    assert [sorted(cells) for cells in descent.adjacency] == [[2], [2], [0, 1]]
