"""Unit tests for the solver-agnostic surface-conditioning kernel + QC primitives."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.surface_conditioning import (
    SurfaceConditioningInput,
    accumulation_budget,
    boundary_cells,
    classify_depressions,
    condition_surface_top,
    steepest_descent_accumulation,
)

# A 5-cell line A-B-C-D with an inactive E off A (the outlet ring):
#   idx 0 A=0 outlet, 1 B=5, 2 C=2 (a pit below both neighbours), 3 D=8, 4 E inactive.
_ADJ = [{1, 4}, {0, 2}, {1, 3}, {2}, {0}]
_ACTIVE = np.array([True, True, True, True, False])
_XC = np.array([0.0, 1.0, 2.0, 3.0, -1.0])
_YC = np.zeros(5)
_AREAS = np.array([1.0, 1.0, 1.0, 1.0, 0.0])


def _base_input(top, **kw):
    return SurfaceConditioningInput(
        top=np.asarray(top, float), active=_ACTIVE, adjacency=_ADJ, **kw
    )


def test_fills_interior_pit_so_it_drains():
    top = [0.0, 5.0, 2.0, 8.0, np.nan]
    res = condition_surface_top(_base_input(top), epsilon=1e-3)
    # The pit C rises just above its spill neighbour B so it drains B -> A.
    assert res.top[2] == pytest.approx(5.001, abs=1e-6)
    assert res.raised[2]
    assert res.info["unreached_active"] == 0
    # No pit remains on the conditioned graph.
    _, counts = classify_depressions(
        res.top, active=_ACTIVE, adjacency=_ADJ, xc=_XC, yc=_YC, boundary={0}
    )
    assert counts["pits"] == 0


def test_control_cell_is_pinned_and_drained_into():
    top = [0.0, 5.0, 2.0, 8.0, np.nan]
    res = condition_surface_top(_base_input(top, control_cells={2: 2.0}), epsilon=1e-3)
    # C is a fixed low: it keeps its level and is never raised; D drains into it.
    assert res.top[2] == pytest.approx(2.0)
    assert not res.raised[2]
    _, counts = classify_depressions(
        res.top,
        active=_ACTIVE,
        adjacency=_ADJ,
        xc=_XC,
        yc=_YC,
        boundary={0},
        control_cells={2},
    )
    assert counts["pits"] == 0
    assert counts["control_minima"] == 1


def test_control_cell_below_top_lowers_it():
    top = [0.0, 5.0, 9.0, 8.0, np.nan]  # C sampled high at 9
    res = condition_surface_top(_base_input(top, control_cells={2: 3.0}), epsilon=1e-3)
    assert res.top[2] == pytest.approx(3.0)  # pinned to the thalweg, below its sampled top


def test_floor_is_not_violated_by_a_raise_only_fill():
    top = [0.0, 5.0, 2.0, 8.0, np.nan]
    floor = np.array([-1.0, -1.0, -1.0, -1.0, np.nan])
    res = condition_surface_top(_base_input(top, floor=floor), epsilon=1e-3)
    assert res.info["floor_violations"] == 0.0


def test_isolated_basin_reports_unreached():
    # Two mutually-adjacent active cells with no boundary and no control never
    # get a base level to drain to.
    adj = [{1}, {0}]
    active = np.array([True, True])
    res = condition_surface_top(
        SurfaceConditioningInput(top=np.array([3.0, 4.0]), active=active, adjacency=adj)
    )
    assert res.info["unreached_active"] == 2


def test_boundary_cells_detects_the_outlet_ring():
    assert boundary_cells(_ACTIVE, _ADJ) == {0}


def test_accumulation_budget_closes_after_conditioning():
    top = [0.0, 5.0, 2.0, 8.0, np.nan]
    res = condition_surface_top(_base_input(top), epsilon=1e-3)
    flow = steepest_descent_accumulation(
        res.top,
        active=_ACTIVE,
        adjacency=_ADJ,
        xc=_XC,
        yc=_YC,
        areas=_AREAS,
        boundary={0},
    )
    budget = accumulation_budget(flow)
    # Every active cell's area exits through the single boundary outlet; nothing stranded.
    assert budget["acc_stranded"] == pytest.approx(0.0)
    assert budget["acc_boundary"] == pytest.approx(4.0)


def test_input_top_is_not_mutated():
    top = np.array([0.0, 5.0, 2.0, 8.0, np.nan])
    original = top.copy()
    condition_surface_top(_base_input(top), epsilon=1e-3)
    np.testing.assert_array_equal(np.nan_to_num(top), np.nan_to_num(original))
