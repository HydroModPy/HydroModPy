"""The per-cell discharge is routed on the descent D of the build, nothing else.

The graph was once the steepest descent of the unfilled top, rebuilt per
extraction with a per-output neighbourhood. It is now D's receivers: a pit of
the top no longer holds the water above it, a diagonal talweg is followed on a
quad mesh, and a river CHD passes the water on, so the outlet keeps the
domain sum.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.discharge_routing import (
    route_release_to_discharge,
    routing_graph_for_model,
)
from hydromodpy.solver.modflow_common.mesh_descent import build_solver_mesh_descent
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def _model(top: np.ndarray, base_level: np.ndarray | None = None) -> SimpleNamespace:
    nrow, ncol = top.shape
    mesh = SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top,
        botm=np.full((1, nrow, ncol), -10.0),
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


def _receiver_pairs(graph) -> set[tuple[int, int]]:
    return {
        tuple(sorted((cell, int(receiver))))
        for cell, receiver in enumerate(graph.downstream)
        if receiver >= 0
    }


def test_the_graph_is_the_receivers_of_d() -> None:
    model = _model(np.arange(25, dtype=float).reshape(5, 5))

    graph = routing_graph_for_model(model)

    assert graph is model.descent.metric.graph


def test_a_pit_of_the_top_does_not_hold_the_release_above_it() -> None:
    # A valley sloping to the south edge with a closed pit in its middle.
    rows, cols = np.mgrid[0:7, 0:7]
    top = 10.0 + 2.0 * (6 - rows) + np.abs(cols - 3)
    top[3, 3] = 0.0
    model = _model(top.astype(float))
    graph = routing_graph_for_model(model)
    release = np.ones(49)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=np.ones(49, bool))

    pit = 3 * 7 + 3
    assert graph.downstream[pit] >= 0
    sinks = np.flatnonzero(np.asarray(graph.downstream) < 0)
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) > float(accumulated[pit])


def test_a_diagonal_talweg_is_followed_on_a_quad_mesh() -> None:
    n = 30
    rows, cols = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    top = 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)
    model = _model(top)

    graph = routing_graph_for_model(model)

    diagonal = {
        tuple(sorted((r * n + c, (r + 1) * n + (c + 1))))
        for r in range(n - 1)
        for c in range(n - 1)
    }
    assert _receiver_pairs(graph) & diagonal
    assert model.descent.diagonal_neighbors


def test_a_stream_chd_inside_the_catchment_passes_the_water_to_the_outlet() -> None:
    # A valley sloping south, its river column held by a stream-role CHD that
    # carries all the release, as the release union counts it.
    n = 11
    rows, cols = np.mgrid[0:n, 0:n]
    top = 50.0 + 2.0 * np.abs(cols - 5) + 1.0 * (n - 1 - rows)
    river = (cols == 5).reshape(-1)
    model = _model(top.astype(float), base_level=river)
    graph = routing_graph_for_model(model)
    release = np.where(river, 1.0, 0.0)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=np.ones(n * n, bool))

    outlet = int(np.argmax(accumulated))
    assert model.descent.constant_head[river].all()
    assert float(accumulated[outlet]) == pytest.approx(float(release.sum()))
    assert np.all(graph.downstream[river & (np.arange(n * n) != outlet)] >= 0)
