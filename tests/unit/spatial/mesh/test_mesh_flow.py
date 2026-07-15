"""Unit tests for the solver-agnostic mesh flow primitives."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.ops.mesh_flow import (
    flow_accumulation,
    lowest_unvisited_neighbour,
    steepest_descent_receiver,
)


def _chain(n: int):
    top = np.array([100.0 - i for i in range(n)])
    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n - 1):
        adj[i].add(i + 1)
        adj[i + 1].add(i)
    cen = np.array([[i * 10.0, 0.0] for i in range(n)])
    return top, adj, cen


def test_steepest_descent_receiver_on_a_chain() -> None:
    top, adj, cen = _chain(6)
    recv = steepest_descent_receiver(top, adj, cen)
    assert recv.tolist() == [1, 2, 3, 4, 5, -1]  # each cell drains to its lower neighbour


def test_flow_accumulation_on_a_chain() -> None:
    top, adj, cen = _chain(6)
    recv = steepest_descent_receiver(top, adj, cen)
    assert flow_accumulation(recv).tolist() == [1, 2, 3, 4, 5, 6]


def test_receiver_skips_inactive_neighbours() -> None:
    top, adj, cen = _chain(4)
    active = np.array([True, True, False, True])
    recv = steepest_descent_receiver(top, adj, cen, active=active)
    assert recv[1] == -1  # cell 1's only downhill neighbour (2) is inactive -> a sink
    assert recv[2] == -1  # inactive cells get no receiver


def test_lowest_unvisited_neighbour_spills_over_a_pit() -> None:
    top = np.array([100.0, 96.0, 99.0])  # cell 1 is a pit
    adj = [{1}, {0, 2}, {1}]
    active = np.array([True, True, True])
    # from the pit at cell 1, the lowest neighbour not already walked is cell 2 (99 < 100)
    assert lowest_unvisited_neighbour(1, adj, top, active, visited={0, 1}) == 2
    # everything visited -> no spill
    assert lowest_unvisited_neighbour(1, adj, top, active, visited={0, 1, 2}) is None
