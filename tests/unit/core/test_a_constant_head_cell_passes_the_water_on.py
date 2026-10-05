"""A constant-head cell keeps its steepest descent; the walks that stop there read -1.

The cell sits on a slope, so the steepest descent hands it a lower neighbour.
D sends its upslope cells into it and keeps that receiver, so an accumulation
crosses a river CHD and the outlet still sums the domain. The drainage mover
and the reach rectification stop where water leaves the model: they read the
stopping receiver, -1 on the constant-head cells.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from tests.unit.core._descent_meshes import grid_descent

N = 7
HEAD = 3 * N + 3


def _slope() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 10.0 + rows + 0.1 * cols


def _head_at(cell: int) -> np.ndarray:
    base_level = np.zeros(N * N, dtype=bool)
    base_level[cell] = True
    return base_level


def test_the_constant_head_cell_keeps_its_steepest_descent() -> None:
    plain = grid_descent(_slope())

    descent = grid_descent(_slope(), base_level=_head_at(HEAD))

    assert descent.constant_head[HEAD]
    assert int(descent.constant_head.sum()) == 1
    assert int(descent.receiver[HEAD]) == int(plain.receiver[HEAD]) >= 0
    assert np.isfinite(descent.metric.edge_length[HEAD])
    assert int(descent.receiver[HEAD + N]) == HEAD


def test_a_walk_that_must_stop_there_reads_minus_one() -> None:
    descent = grid_descent(_slope(), base_level=_head_at(HEAD))

    stopping = descent.stopping_receiver

    assert int(stopping[HEAD]) == -1
    others = np.arange(N * N) != HEAD
    assert np.array_equal(stopping[others], descent.receiver[others])


def test_the_accumulation_crosses_the_constant_head_cell() -> None:
    descent = grid_descent(_slope(), base_level=_head_at(HEAD))

    accumulated = accumulate_on_downhill_graph(descent.metric.graph, np.ones((1, N * N)))[0]

    outlets = descent.routable & (descent.receiver < 0)
    assert np.isclose(accumulated[outlets].sum(), N * N)
    assert accumulated[int(descent.receiver[HEAD])] > accumulated[HEAD]
