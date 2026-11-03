"""The LAK connections of a lake over a stack with pass-through cells.

A pass-through cell (``idomain = -1``) has no thickness: the pinch-out hands it to
the active cell next to it. The lake counts its occupied layers in grid layers, so
a column whose occupied layer is pinched out holds no lake water inside the stack
and leaks through its bed into the first active cell below. A bank connection
joins the lake water of a column to every active cell of a neighbor column that
holds part of that water band, whatever its layer. A column left with no active
cell under the lake is refused.

The grid is one row of three 10 m cells, the lake on the middle one.
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import apply_lake_idomain_mask, build_lake_connectiondata
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

LAKE = [1]


def _row(top: list[float], botm: list[list[float]], idomain: list[list[int]]) -> SolverMesh:
    """Three cells in a row; ``botm`` and ``idomain`` hold one list per layer."""
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=3,
        top=np.array([top], dtype=float),
        botm=np.array([[layer] for layer in botm], dtype=float),
        dx=10.0,
        dy=10.0,
    )
    return dataclasses.replace(mesh, idomain=np.array(idomain, dtype=int))


def _rows(mesh: SolverMesh, **kwargs) -> list[list]:
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": LAKE})
    return build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=LAKE, bedleak=1e-6, solver_mesh=masked, **kwargs
    )


def _banks(rows: list[list]) -> set[tuple[tuple[int, int], float, float]]:
    return {(tuple(r[2]), r[5], r[6]) for r in rows if r[3] == "HORIZONTAL"}


def _vertical(rows: list[list]) -> list[tuple[int, int]]:
    return [tuple(r[2]) for r in rows if r[3] == "VERTICAL"]


def test_a_lake_column_with_a_pinched_cap_leaks_through_its_bed_only(caplog) -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[7.0, 10.0, 7.0], [0.0, 0.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, -1, 1], [1, 1, 1], [1, 1, 1]],
    )
    with caplog.at_level(logging.INFO):
        rows = _rows(mesh)
    assert _vertical(rows) == [(1, 1)]
    assert _banks(rows) == set()
    assert "occupy pass-through cells only" in caplog.text


def test_a_bank_reaches_the_active_cell_under_a_pinched_neighbour() -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[10.0, 7.0, 7.0], [0.0, 0.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[-1, 1, 1], [1, 1, 1], [1, 1, 1]],
    )
    rows = _rows(mesh)
    assert _vertical(rows) == [(1, 1)]
    assert _banks(rows) == {((1, 0), 7.0, 10.0), ((0, 2), 7.0, 10.0)}


def test_a_bank_follows_the_lake_water_across_the_layers_of_a_higher_neighbour() -> None:
    mesh = _row(
        top=[14.0, 10.0, 10.0],
        botm=[[9.0, 7.0, 7.0], [0.0, 0.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, 1, 1], [1, 1, 1], [1, 1, 1]],
    )
    banks = _banks(_rows(mesh))
    assert banks == {((0, 0), 9.0, 10.0), ((1, 0), 7.0, 9.0), ((0, 2), 7.0, 10.0)}
    # The two rows of the higher neighbor share the lake water band [7, 10] exactly.
    assert sum(t - b for (cell, b, t) in banks if cell[1] == 0) == pytest.approx(3.0)


def test_a_flat_stack_keeps_one_bank_per_occupied_layer() -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[7.0, 7.0, 7.0], [4.0, 4.0, 4.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, 1, 1], [1, 1, 1], [1, 1, 1]],
    )
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": LAKE}, occupied_layers=2)
    rows = build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=LAKE, bedleak=1e-6, solver_mesh=masked, occupied_layers=2
    )
    assert _vertical(rows) == [(2, 1)]
    assert _banks(rows) == {
        ((0, 0), 7.0, 10.0),
        ((0, 2), 7.0, 10.0),
        ((1, 0), 4.0, 7.0),
        ((1, 2), 4.0, 7.0),
    }


@pytest.mark.parametrize("below", [-1, 0], ids=["pass_through", "inactive"])
def test_a_lake_column_with_no_active_cell_below_is_refused(below: int) -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[7.0, -10.0, 7.0], [0.0, -10.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, 1, 1], [1, below, 1], [1, below, 1]],
    )
    with pytest.raises(ValueError, match=r"lakes\.lake leaves 1 column\(s\) with no active cell"):
        apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": LAKE})


def test_the_refusal_names_the_pinch_out_remedies() -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[7.0, -10.0, 7.0], [0.0, -10.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, 1, 1], [1, -1, 1], [1, -1, 1]],
    )
    with pytest.raises(ValueError) as refused:
        apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": LAKE})
    message = str(refused.value)
    assert "first cell 1" in message
    assert "min_thickness" in message
    assert 'pinch_out = "keep_min_thickness"' in message


def test_a_marnage_lake_leaks_into_the_top_active_cell_under_a_pinched_layer() -> None:
    mesh = _row(
        top=[10.0, 10.0, 10.0],
        botm=[[7.0, 10.0, 7.0], [0.0, 0.0, 0.0], [-10.0, -10.0, -10.0]],
        idomain=[[1, -1, 1], [1, 1, 1], [1, 1, 1]],
    )
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=LAKE,
        bedleak=1e-6,
        solver_mesh=mesh,
        dynamic_area=True,
        bank_seepage=False,
    )
    assert _vertical(rows) == [(1, 1)]
