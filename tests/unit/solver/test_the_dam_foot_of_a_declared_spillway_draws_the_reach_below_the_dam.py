"""The dam foot the production resolver gives draws the reach the saddle leaves out.

On the dammed valley of ``_heads_dam`` the criterion leaves the reservoir through
a saddle lower than the dam, so the reach below the dam has no head. The lake
declares a spillway routed to the downstream reach: ``resolve_spillway_seed_cells``
finds the crest cell below its shore nearest the outlet, ``resolve_dam_foot_cells``
keeps it, and forcing it draws the reach. A lake without a declared spillway has
no foot, so it forces nothing (its exit is the saddle D already takes).
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow6.builders import lake as lake_builder
from hydromodpy.solver.modflow6.builders.lake import resolve_spillway_seed_cells
from hydromodpy.solver.modflow_common.mesh_descent import resolve_dam_foot_cells
from hydromodpy.spatial.mesh.model.cell_adjacency import build_planar_cell_adjacency
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent
from tests.unit.core._heads_dam import (
    AXIS,
    CELL,
    DAM_FOOT_ROW,
    N_COLS,
    N_ROWS,
    cell,
    centre,
    dam_geometry,
    topography,
)

LAKE_CELLS = [cell(row, col) for row in range(8, 12) for col in range(5, 8)]


def _dam_foot(monkeypatch, *, declared: bool) -> dict[str, int]:
    outlets = [{"mover": {"to_downstream_reach": True}}] if declared else []
    monkeypatch.setattr(
        lake_builder, "_active_lake_definitions", lambda model: {"res": {"outlets": outlets}}
    )
    n_cells = N_ROWS * N_COLS
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    planar = type("Planar", (), {"flat_connectivity": connectivity, "vertices": vertices})()
    centroids = np.asarray([centre(*divmod(c, N_COLS)) for c in range(n_cells)])
    seeds = resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": LAKE_CELLS},
        cell_adjacency=build_planar_cell_adjacency(planar, n_cells),
        cell_centroids=centroids,
        idomain=np.ones((1, n_cells), dtype=int),
        mesh_top=topography(),
        outlet_xy=centre(N_ROWS - 1, AXIS),
    )
    lake_of = np.full(n_cells, -1, dtype=int)
    lake_of[LAKE_CELLS] = 0
    descent = grid_descent(topography().reshape(N_ROWS, N_COLS), lake_of=lake_of)
    return resolve_dam_foot_cells(descent, seeds)


def test_a_declared_spillway_gives_the_crest_below_the_lake_as_the_foot(monkeypatch) -> None:
    feet = _dam_foot(monkeypatch, declared=True)

    assert feet == {"res": cell(12, AXIS)}


def test_the_reach_below_the_dam_is_drawn_with_that_foot_and_missing_without(monkeypatch) -> None:
    feet = _dam_foot(monkeypatch, declared=True)
    below_dam = cell(DAM_FOOT_ROW, AXIS)

    plain = dam_geometry()
    forced = dam_geometry(list(feet.values()))

    assert not plain.observed[below_dam]
    assert forced.observed[below_dam]
    downstream = forced.metric.graph.downstream
    walk = below_dam
    while walk >= 0:
        assert forced.observed[walk]
        walk = int(downstream[walk])
    assert forced.observed[forced.outlet]
    assert forced.diagnostics["n_forced_heads"] == 1.0
    assert not (plain.observed & ~forced.observed).any()


def test_a_lake_without_a_declared_spillway_has_no_foot_to_force(monkeypatch) -> None:
    assert _dam_foot(monkeypatch, declared=False) == {}
