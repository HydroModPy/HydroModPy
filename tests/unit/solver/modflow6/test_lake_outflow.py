"""The cell below a dam where a lake spillway leaves the aquifer (dam foot).

The foot is the crest cell below the shore cell nearest the outlet (m). With a cutoff wall
that has the lake on its left, the foot is taken among the cells on its right.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.solver.modflow6.builders import lake_outflow as lake_builder
from hydromodpy.solver.modflow6.builders.lake_outflow import resolve_spillway_seed_cells
from hydromodpy.solver.modflow_common.flow_directions import resolve_dam_foot_cells
from tests._helpers.descent_cases import grid_descent
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.catchment.stream_network._heads_dam import (
    AXIS,
    CELL,
    N_COLS,
    N_ROWS,
    cell,
    centre,
    topography,
)

LAKE_CELLS = [cell(row, col) for row in range(8, 12) for col in range(5, 8)]

# The wall runs north along x = 15 m, the lake (x < 15 m) is on its left.
WALL = LineString([(15.0, -50.0), (15.0, 50.0)])
# Lake {0, 1}. Shore cell 1 touches cell 2 (a bank on the lake side, x = 10 m, the lowest)
# and cell 3 (downstream of the wall, x = 20 m).
CENTROIDS = [[0, 0], [10, 0], [10, 10], [20, 0]]
ADJACENCY = [{1}, {0, 2, 3}, {1}, {1}]
TOP_M = [100.0, 95.0, 70.0, 80.0]


def declare_spillway(monkeypatch, *, declared: bool = True, wall: LineString | None = None) -> None:
    definition = {"outlets": [{"mover": {"to_downstream_reach": True}}] if declared else []}
    if wall is not None:
        definition["cutoff_wall_line"] = wall
    monkeypatch.setattr(lake_builder, "_active_lake_definitions", lambda model: {"res": definition})


def dammed_valley_foot(monkeypatch, *, declared: bool) -> dict[str, int]:
    declare_spillway(monkeypatch, declared=declared)
    n_cells = N_ROWS * N_COLS
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    planar = HydroMesh(
        vertices=vertices[:, :2], cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),)
    )
    seeds = resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": LAKE_CELLS},
        cell_adjacency=derive_geometry(planar).adjacency_sets(),
        cell_centroids=np.asarray([centre(*divmod(c, N_COLS)) for c in range(n_cells)]),
        idomain=np.ones((1, n_cells), dtype=int),
        mesh_top=topography(),
        outlet_xy=centre(N_ROWS - 1, AXIS),
    )
    lake_of = np.full(n_cells, -1, dtype=int)
    lake_of[LAKE_CELLS] = 0
    descent = grid_descent(topography().reshape(N_ROWS, N_COLS), lake_of=lake_of)
    return resolve_dam_foot_cells(descent, seeds)


def seed_cells(monkeypatch, *, centroids=CENTROIDS, adjacency=ADJACENCY, top=TOP_M):
    declare_spillway(monkeypatch, wall=WALL)
    return resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": [0, 1]},
        cell_adjacency=adjacency,
        cell_centroids=np.asarray(centroids, dtype=float),
        idomain=np.ones((1, len(top)), dtype=int),
        mesh_top=np.asarray(top, dtype=float),
        outlet_xy=(30.0, 0.0),
    )


# The dammed valley leaves the reservoir through a saddle lower than the dam, so the reach
# below the dam has no head unless the spillway foot is forced.
@pytest.mark.parametrize(
    ("declared", "feet"),
    [
        pytest.param(True, {"res": cell(12, AXIS)}, id="crest below the lake"),
        pytest.param(False, {}, id="no declared spillway"),
    ],
)
def test_dam_foot_of_a_valley(monkeypatch, declared, feet) -> None:
    assert dammed_valley_foot(monkeypatch, declared=declared) == feet


def test_foot_is_downstream_of_the_wall(monkeypatch) -> None:
    assert seed_cells(monkeypatch) == {"res": 3}


def test_refuses_a_foot_on_the_lake_side(monkeypatch) -> None:
    # The only non-lake neighbor is on the lake side: there is no foot below the wall.
    with pytest.raises(ValueError, match="downstream of the cutoff wall"):
        seed_cells(
            monkeypatch,
            centroids=[[0, 0], [10, 0], [10, 10]],
            adjacency=[{1}, {0, 2}, {1}],
            top=[100, 95, 70],
        )
