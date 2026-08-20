"""Unit tests for the prebuilt downhill routing graph and stack helpers."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    build_downhill_graph,
    drain_budget_stack_to_positive_outflow,
    drain_budget_to_positive_outflow,
)


def _quad_mesh(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, face_node_connectivity) for a structured quad mesh."""
    nodes_per_row = ncol + 1
    connectivity = np.empty((nrow * ncol, 4), dtype=int)
    for row in range(nrow):
        for col in range(ncol):
            node = row * nodes_per_row + col
            connectivity[row * ncol + col] = (
                node,
                node + 1,
                node + nodes_per_row + 1,
                node + nodes_per_row,
            )
    xx, yy = np.meshgrid(np.arange(ncol + 1, dtype="float64"), np.arange(nrow + 1, dtype="float64"))
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    return vertices, connectivity


def test_graph_accumulation_matches_per_timestep_routing() -> None:
    rng = np.random.default_rng(3)
    vertices, connectivity = _quad_mesh(6, 5)
    n_cells = 30
    reference = rng.normal(100.0, 10.0, n_cells)
    reference[rng.random(n_cells) < 0.1] = np.nan
    inactive = rng.random(n_cells) < 0.15
    stack = rng.normal(0.0, 1.0, (9, n_cells))
    stack[rng.random((9, n_cells)) < 0.05] = np.nan

    graph = build_downhill_graph(reference, connectivity, vertices=vertices, inactive_mask=inactive)
    routed_stack = accumulate_on_downhill_graph(graph, stack)

    per_timestep = np.stack(
        [accumulate_on_downhill_graph(graph, stack[t]) for t in range(stack.shape[0])]
    )
    assert np.allclose(routed_stack, per_timestep, equal_nan=True)


def test_graph_accumulation_single_field_shape() -> None:
    vertices, connectivity = _quad_mesh(3, 3)
    reference = np.arange(9, dtype="float64")[::-1]
    graph = build_downhill_graph(reference, connectivity, vertices=vertices)
    routed = accumulate_on_downhill_graph(graph, np.ones(9))
    assert routed.shape == (9,)
    # Total accumulated load at the single outlet equals the summed sources.
    assert np.nanmax(routed) == pytest.approx(9.0)


def test_graph_accumulation_all_inactive_returns_zeros() -> None:
    _, connectivity = _quad_mesh(2, 2)
    reference = np.full(4, np.nan)
    graph = build_downhill_graph(reference, connectivity)
    routed = accumulate_on_downhill_graph(graph, np.ones((3, 4)))
    assert routed.shape == (3, 4)
    assert (routed == 0.0).all()


def test_graph_accumulation_rejects_cell_mismatch() -> None:
    _, connectivity = _quad_mesh(2, 2)
    graph = build_downhill_graph(np.arange(4, dtype="float64"), connectivity)
    with pytest.raises(ValueError, match="cells"):
        accumulate_on_downhill_graph(graph, np.ones((3, 5)))


def test_drain_stack_matches_per_timestep_helper() -> None:
    rng = np.random.default_rng(5)
    n_timesteps, n_layers, n_cells = 6, 2, 14
    stack = rng.normal(0.0, 1.0, (n_timesteps, n_layers, n_cells))
    stack[rng.random(stack.shape) < 0.1] = np.nan
    stack[rng.random(stack.shape) < 0.05] = -99999.0

    batched = drain_budget_stack_to_positive_outflow(stack, n_cells=n_cells)
    per_timestep = np.stack(
        [drain_budget_to_positive_outflow(stack[t], n_cells=n_cells) for t in range(n_timesteps)]
    )
    assert np.allclose(batched, per_timestep, equal_nan=True)


def test_drain_stack_all_positive_fallback_is_per_timestep() -> None:
    # One timestep uses the outflow-positive sign convention, the other the
    # standard negative convention; the fallback must not leak across rows.
    stack = np.array(
        [
            [[1.0, 2.0, 3.0]],
            [[-1.0, -2.0, 0.0]],
        ]
    )
    batched = drain_budget_stack_to_positive_outflow(stack, n_cells=3)
    assert np.allclose(batched[0], [1.0, 2.0, 3.0])
    assert np.allclose(batched[1], [1.0, 2.0, 0.0])
