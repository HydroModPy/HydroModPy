"""``diagonal_neighbors=True`` on the routing-graph entry point must go D8.

``routing_graph_for_model`` used to call the shared-EDGE adjacency builder on
its ``True`` branch too, the same fallback ``build_downhill_graph`` already
uses when no adjacency is passed at all. The flag toggled nothing: asking for
D8 silently gave back D4, on a structured mesh whose diagonal cells share a
node and never an edge.

Reuses the diagonal-valley construction of
``tests.unit.core.test_a_diagonal_talweg_needs_diagonal_neighbours``, through
the same ``SolverMesh``-backed model fixture ``test_discharge_routing`` uses,
so this exercises the real entry point instead of the graph builder directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_common.discharge_routing import routing_graph_for_model
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

N = 30


def _diagonal_valley_model() -> SimpleNamespace:
    """A V-shaped valley whose talweg runs along the grid diagonal."""
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)
    botm = np.full((N, N), -10.0, dtype=float)
    mesh = SolverMesh.from_structured_arrays(
        nrow=N,
        ncol=N,
        top=top,
        botm=np.stack([botm]),
    )
    return SimpleNamespace(solver_mesh=mesh)


def _diagonal_neighbor_pairs() -> set[tuple[int, int]]:
    pairs = set()
    for row in range(N):
        for col in range(N):
            cell = row * N + col
            for row_shift, col_shift in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                near_row, near_col = row + row_shift, col + col_shift
                if 0 <= near_row < N and 0 <= near_col < N:
                    pairs.add(tuple(sorted((cell, near_row * N + near_col))))
    return pairs


def test_diagonal_neighbors_true_actually_builds_diagonal_edges():
    model = _diagonal_valley_model()

    graph = routing_graph_for_model(model, diagonal_neighbors=True)

    diagonal_pairs = _diagonal_neighbor_pairs()
    receiver_pairs = {
        tuple(sorted((cell, int(receiver))))
        for cell, receiver in enumerate(graph.downstream)
        if receiver >= 0
    }
    assert receiver_pairs & diagonal_pairs


def test_diagonal_neighbors_false_takes_no_diagonal_step():
    model = _diagonal_valley_model()

    graph = routing_graph_for_model(model, diagonal_neighbors=False)

    diagonal_pairs = _diagonal_neighbor_pairs()
    receiver_pairs = {
        tuple(sorted((cell, int(receiver))))
        for cell, receiver in enumerate(graph.downstream)
        if receiver >= 0
    }
    assert not (receiver_pairs & diagonal_pairs)
