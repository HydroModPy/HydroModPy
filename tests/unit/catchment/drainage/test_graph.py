from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

import hydromodpy.catchment.stream_network.geometry as stream_geometry_module
from hydromodpy.catchment.drainage.distance import shared_node_adjacency
from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph, build_downhill_graph
from hydromodpy.catchment.stream_network.geometry import NetworkGeometry, build_network_geometry
from hydromodpy.core.budget.flux import budget_outflow, budget_outflow_stack
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.catchment.stream_network._heads_valley import (
    AXIS,
    CELL,
    N_COLS,
    N_ROWS,
    candidates,
    cell,
    centre,
    valley_geometry,
)

# A free end is judged by the talweg within its radius, not by its nearest cell.
#
# A mapped line runs beside the model talweg, so the cell nearest to a
# confluence is often a hillside cell. Here the reach end sits three cells off
# the axis: its nearest cell drains less than the head's axis cell, and a
# nearest-cell rule would drop the head. Within the 50 m radius the end reads
# the axis further down, which drains more, so the head is kept.


def test_a_head_reads_the_drained_area_within_its_radius() -> None:
    head, junction = centre(5, AXIS), centre(20, AXIS + 3)

    geometry = valley_geometry(candidates([(head, junction)]), snap_radius_m=50.0)

    drained = accumulate_on_downhill_graph(
        geometry.metric.graph, np.full(N_ROWS * N_COLS, CELL * CELL)
    )
    assert drained[cell(20, AXIS + 3)] < drained[cell(5, AXIS)]
    assert geometry.heads is not None
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
    assert geometry.observed[cell(5, AXIS)]


# Unit tests for the prebuilt downhill routing graph and stack helpers.


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

    batched = budget_outflow_stack(stack, n_cells=n_cells)
    per_timestep = np.stack([budget_outflow(stack[t], n_cells=n_cells) for t in range(n_timesteps)])
    assert np.allclose(batched, per_timestep, equal_nan=True)


def test_a_positive_flux_enters_the_aquifer_at_every_step() -> None:
    # No reader guesses a sign: an all-positive step is water that enters.
    stack = np.array(
        [
            [[1.0, 2.0, 3.0]],
            [[-1.0, -2.0, 0.0]],
        ]
    )
    batched = budget_outflow_stack(stack, n_cells=3)
    assert np.allclose(batched[0], [0.0, 0.0, 0.0])
    assert np.allclose(batched[1], [1.0, 2.0, 0.0])


# Unit tests for injecting a prebuilt cell adjacency into the downhill graph.


def test_adjacency_length_is_validated() -> None:
    _, connectivity = quad_mesh(2, 2)
    reference = np.arange(4, dtype="float64")

    with pytest.raises(ValueError, match="adjacency must have 4 entries"):
        build_downhill_graph(reference, connectivity, adjacency=[set(), set()])

    # The guard sits before the all-inactive shortcut, so a wrong length is
    # reported whatever the surface looks like.
    with pytest.raises(ValueError, match="adjacency must have 4 entries"):
        build_downhill_graph(
            np.full(4, np.nan),
            connectivity,
            adjacency=[set(), set()],
        )


# ``build_network_geometry`` must not rebuild the adjacency it already paid for.
#
# The function builds the neighbor graph once to flood the model top from the
# domain border (:func:`fill_depressions_on_graph`) before descending it. Handing that
# same graph to the downslope metric instead of letting it rebuild its own is
# what makes ``diagonal_neighbors=True`` affordable on a real mesh: two probes
# meant to compare a D4 and a D8 descent both exhausted memory rebuilding the
# eight-neighbor graph a second time, on two different DEMs.

N_ROWS_built_once = 6
N_COLS_built_once = 4
N_CELLS = N_ROWS_built_once * N_COLS_built_once
CELL_SIZE_built_once = 10.0


def _ramp() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A surface with no depression at all: every cell already has a strictly lower neighbor."""
    vertices, connectivity = quad_mesh(
        N_ROWS_built_once, N_COLS_built_once, cell_size=CELL_SIZE_built_once
    )
    rows = np.repeat(np.arange(N_ROWS_built_once, dtype=float), N_COLS_built_once)
    elevation = 100.0 - rows
    return vertices, connectivity, elevation


def _build(*, diagonal_neighbors: bool, delineated_catchment: np.ndarray | None) -> NetworkGeometry:
    vertices, connectivity, elevation = _ramp()
    observed = np.zeros(N_CELLS, dtype=bool)
    observed[(N_ROWS_built_once - 1) * N_COLS_built_once :] = True
    return build_network_geometry(
        topography=elevation,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(N_CELLS, CELL_SIZE_built_once * CELL_SIZE_built_once),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=1e-4,
        delineated_catchment=delineated_catchment,
        diagonal_neighbors=diagonal_neighbors,
    )


def _counting(
    original: Callable[..., list[set[int]]],
) -> tuple[dict[str, int], Callable[..., list[set[int]]]]:
    """A wrapper that still does the real construction, but counts the calls."""
    calls = {"n": 0}

    def wrapper(*args: object, **kwargs: object) -> list[set[int]]:
        calls["n"] += 1
        return original(*args, **kwargs)

    return calls, wrapper


class TestTheGraphFollowsTheAdjacencyItWasGiven:
    def test_a_disconnected_adjacency_strands_the_descent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The graph the metric descends must be the one the flood just used.

        The ramp has no depression, so a disconnected adjacency changes nothing
        for the flood: this isolates the one place left where the adjacency
        can still matter, the metric. If the descent still reaches the whole
        catchment despite it, the metric rebuilt its own, correct graph instead
        of receiving this one, which is the bug this file pins.
        """
        catchment = np.ones(N_CELLS, dtype=bool)
        baseline = _build(diagonal_neighbors=True, delineated_catchment=catchment)
        assert baseline.frac_reachable_obs_raw == pytest.approx(1.0)

        def _disconnected(face_node_connectivity: np.ndarray, *, n_cells: int) -> list[set[int]]:
            return [set() for _ in range(n_cells)]

        monkeypatch.setattr(stream_geometry_module, "shared_node_adjacency", _disconnected)

        broken = _build(diagonal_neighbors=True, delineated_catchment=catchment)

        assert broken.frac_reachable_obs_raw < 0.5
