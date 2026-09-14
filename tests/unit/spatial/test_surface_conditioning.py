"""Unit tests for the solver-agnostic surface-conditioning kernel + QC primitives."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.surface_conditioning import (
    SurfaceConditioningInput,
    accumulation_budget,
    boundary_cells,
    breach_channel_corridor,
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


# -- Channel breach (network safety net) --------------------------------------

# Channel chain 0-1-2-3 draining right to outlet 3; cell 1 is a local low.
_CH_ADJ = [{1}, {0, 2}, {1, 3}, {2}]


def test_breach_carves_a_local_low_monotone():
    top = np.array([10.0, 8.0, 9.0, 5.0])  # 1 (8) sits below its downstream 2 (9)
    carved, info = breach_channel_corridor(
        top, adjacency=_CH_ADJ, channel_cells=[0, 1, 2, 3], outlet_cells=[3], epsilon=0.1
    )
    assert all(carved[i] > carved[i + 1] for i in range(3))  # strictly descending
    assert carved[2] == pytest.approx(7.9)  # 2 lowered below 1 by epsilon
    assert info["cells_lowered"] == 1


def test_breach_leaves_a_descending_channel_untouched():
    top = np.array([10.0, 8.0, 6.0, 4.0])
    carved, info = breach_channel_corridor(
        top, adjacency=_CH_ADJ, channel_cells=[0, 1, 2, 3], outlet_cells=[3], epsilon=0.1
    )
    np.testing.assert_array_equal(carved, top)
    assert info["cells_lowered"] == 0


def test_breach_never_raises_and_respects_the_cap():
    top = np.array([10.0, 8.0, 20.0, 5.0])  # 2 is a big barrier above 1
    carved, _ = breach_channel_corridor(
        top,
        adjacency=_CH_ADJ,
        channel_cells=[0, 1, 2, 3],
        outlet_cells=[3],
        epsilon=0.1,
        max_lowering_m=2.0,
    )
    assert (carved <= top + 1e-12).all()  # lower-only
    assert carved[2] == pytest.approx(18.0)  # capped at top-2.0, not down to 7.9


def test_breach_floor_blocks_overcarving():
    top = np.array([10.0, 8.0, 9.0, 5.0])
    floor = np.array([-1.0, -1.0, 8.5, -1.0])  # cell 2 cannot go below 8.5
    carved, _ = breach_channel_corridor(
        top,
        adjacency=_CH_ADJ,
        channel_cells=[0, 1, 2, 3],
        outlet_cells=[3],
        floor=floor,
        epsilon=0.1,
    )
    assert carved[2] == pytest.approx(8.5)  # floor wins over need (7.9)


# A domain whose every cell is active: the MODFLOW 6 buffered box. No cell has an
# inactive neighbour, so the outlet ring is empty and only the mesh rim can seed
# the flood. Line A-B-C-D, C is a pit; A and D are the two rim ends.
_ADJ_FULL = [{1}, {0, 2}, {1, 3}, {2}]
_ACTIVE_FULL = np.array([True, True, True, True])


def _full_input(top, **kw):
    return SurfaceConditioningInput(
        top=np.asarray(top, float), active=_ACTIVE_FULL, adjacency=_ADJ_FULL, **kw
    )


def test_fully_active_domain_conditions_from_the_mesh_rim():
    # Without a rim the flood cannot start at all: this is the silent no-op that
    # made `condition_top = true` do nothing on the Nancon 25 m box.
    bare = condition_surface_top(_full_input([0.0, 5.0, 2.0, 8.0]), epsilon=1e-3)
    assert bare.info["unreached_active"] == 4
    assert bare.info["cells_raised"] == 0

    res = condition_surface_top(
        _full_input([0.0, 5.0, 2.0, 8.0], rim_cells=frozenset({0, 3})), epsilon=1e-3
    )
    assert res.info["unreached_active"] == 0
    # C drains through D (8.0) or B (5.0); the flood takes the lower spill, B.
    assert res.top[2] == pytest.approx(5.001, abs=1e-6)
    assert res.raised[2]
    # A rim cell is a base level: it is never raised.
    assert not res.raised[0]
    assert not res.raised[3]


def test_mesh_edge_cells_excludes_the_interior():
    from hydromodpy.spatial.mesh.model.cell_adjacency import mesh_edge_cells

    class _PlanarMesh:
        def __init__(self, connectivity):
            self.flat_connectivity = connectivity

    # 3x3 quads over a 4x4 node lattice: only the centre cell (index 4) has all
    # four of its edges shared with a neighbour.
    connectivity = [
        [i * 4 + j, i * 4 + j + 1, (i + 1) * 4 + j + 1, (i + 1) * 4 + j]
        for i in range(3)
        for j in range(3)
    ]
    rim = mesh_edge_cells(_PlanarMesh(connectivity), 9)
    assert rim == frozenset({0, 1, 2, 3, 5, 6, 7, 8})
    assert 4 not in rim
