"""Unit tests for the downslope topographic distance operator."""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
    mean_downslope_distance,
)
from tests._helpers.tolerances import tol
from tests._helpers.ugrid_meshes import quad_mesh

RESOLUTION = 10.0
D4_OVER_D8 = tol("length_ratio_on_a_pure_diagonal_descent")


def _plane(nrow: int, ncol: int) -> np.ndarray:
    """Surface dropping one metre per row, draining to the south."""
    rows = np.arange(nrow, dtype="float64")[:, None]
    return np.broadcast_to(100.0 - rows, (nrow, ncol)).reshape(-1).copy()


def _diagonal_plane(size: int) -> np.ndarray:
    """Surface dropping one metre to the east and one to the south."""
    rows = np.arange(size, dtype="float64")[:, None]
    cols = np.arange(size, dtype="float64")[None, :]
    return (100.0 - rows - cols).reshape(-1)


def _walk_down(metric, target: np.ndarray, start: int) -> float:
    """Follow the descent cell by cell, the naive O(path) reference."""
    n_cells = int(metric.graph.active.size)
    cell = int(start)
    total = 0.0
    for _ in range(n_cells + 1):
        if target[cell]:
            return total
        receiver = int(metric.graph.downstream[cell])
        if receiver < 0:
            return math.inf
        total += float(metric.edge_length[cell])
        cell = receiver
    raise AssertionError("the descent did not terminate: the receiver graph holds a cycle.")


@pytest.mark.parametrize("surface", ["plane", "white_noise"])
def test_reverse_order_visits_receiver_first(surface: str) -> None:
    vertices, connectivity = quad_mesh(20, 20, cell_size=RESOLUTION)
    if surface == "plane":
        reference = _plane(20, 20)
    else:
        reference = np.random.default_rng(7).normal(100.0, 1.0, 400)
    metric = build_downslope_metric(reference, connectivity, vertices=vertices)

    ascending = metric.graph.order[::-1]
    position = np.full(reference.size, -1, dtype=int)
    position[ascending] = np.arange(ascending.size)
    routed = np.flatnonzero(metric.graph.downstream >= 0)

    # The single pass reads d[receiver] and needs it final: every receiver must
    # come strictly earlier than its donor in the traversal order.
    assert np.all(position[metric.graph.downstream[routed]] < position[routed])
    assert np.all(position[routed] >= 0)


@pytest.mark.parametrize("surface", ["plane", "white_noise"])
def test_single_pass_matches_naive_path_walk(surface: str) -> None:
    vertices, connectivity = quad_mesh(20, 20, cell_size=RESOLUTION)
    if surface == "plane":
        reference = _plane(20, 20)
    else:
        reference = np.random.default_rng(13).normal(100.0, 1.0, 400)
    metric = build_downslope_metric(reference, connectivity, vertices=vertices)

    target = np.zeros(400, dtype=bool)
    target[380:] = True  # the southern row
    distance = downslope_distance_to_mask(metric, target)

    walked = np.array([_walk_down(metric, target, cell) for cell in range(400)])
    assert np.allclose(distance, walked, equal_nan=True)


def test_no_cycle_on_exact_plateau() -> None:
    # Four-row plateaus at exactly the same elevation: a tie must never become
    # an edge, otherwise two cells route into each other.
    vertices, connectivity = quad_mesh(20, 5, cell_size=RESOLUTION)
    rows = np.arange(20, dtype="float64")[:, None] // 4
    reference = np.broadcast_to(-rows, (20, 5)).reshape(-1).copy()
    metric = build_downslope_metric(reference, connectivity, vertices=vertices)

    routed = metric.graph.downstream >= 0
    assert np.all(reference[routed] > reference[metric.graph.downstream[routed]])

    target = np.zeros(100, dtype=bool)
    target[-5:] = True
    for cell in range(100):
        _walk_down(metric, target, cell)  # raises if the descent loops


def test_structured_grid_diagonal_descent_length() -> None:
    size = 6
    vertices, connectivity = quad_mesh(size, size, cell_size=RESOLUTION)
    reference = _diagonal_plane(size)
    target = np.zeros(size * size, dtype=bool)
    target[-1] = True  # the south-east corner

    shared_edge = build_downslope_metric(reference, connectivity, vertices=vertices)
    shared_node = build_downslope_metric(
        reference, connectivity, vertices=vertices, diagonal_neighbors=True
    )
    d4 = downslope_distance_to_mask(shared_edge, target)
    d8 = downslope_distance_to_mask(shared_node, target)

    assert d4[0] == pytest.approx(2.0 * RESOLUTION * (size - 1), rel=1e-12)
    assert d8[0] == pytest.approx(math.sqrt(2.0) * RESOLUTION * (size - 1), rel=1e-12)
    assert d4[0] / d8[0] == pytest.approx(D4_OVER_D8, rel=1e-5)


def test_diagonal_neighbors_rejects_a_non_quad_mesh() -> None:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        dtype="float64",
    )
    triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)

    with pytest.raises(ValueError, match="structured quad mesh"):
        build_downslope_metric(
            np.array([2.0, 1.0]), triangles, vertices=vertices, diagonal_neighbors=True
        )


def test_target_cells_have_zero_distance() -> None:
    # A chain where every cell is a target: the zero must be absorbing, so a
    # target upstream of another target keeps 0 instead of one edge length.
    vertices, connectivity = quad_mesh(5, 1, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(5, 1), connectivity, vertices=vertices)

    distance = downslope_distance_to_mask(metric, np.ones(5, dtype=bool))
    assert np.array_equal(distance, np.zeros(5))


def test_empty_target_returns_all_inf() -> None:
    vertices, connectivity = quad_mesh(4, 4, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(4, 4), connectivity, vertices=vertices)

    distance = downslope_distance_to_mask(metric, np.zeros(16, dtype=bool))
    assert np.all(np.isinf(distance))


def test_distance_is_not_symmetric() -> None:
    vertices, connectivity = quad_mesh(4, 1, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(4, 1), connectivity, vertices=vertices)

    upstream = np.array([True, False, False, False])
    downstream = np.array([False, False, False, True])
    to_downstream = downslope_distance_to_mask(metric, downstream)
    to_upstream = downslope_distance_to_mask(metric, upstream)

    assert to_downstream[0] == pytest.approx(3.0 * RESOLUTION, rel=1e-12)
    assert math.isinf(to_upstream[3])


def test_inactive_cells_are_undefined_not_unreachable() -> None:
    vertices, connectivity = quad_mesh(4, 4, cell_size=RESOLUTION)
    inactive = np.zeros(16, dtype=bool)
    inactive[4:8] = True  # a full row cut out of the active surface
    metric = build_downslope_metric(
        _plane(4, 4), connectivity, vertices=vertices, inactive_mask=inactive
    )

    target = np.zeros(16, dtype=bool)
    target[-4:] = True
    distance = downslope_distance_to_mask(metric, target)

    assert np.all(np.isnan(distance[inactive]))
    # The northern row can no longer descend across the cut, so it is defined
    # and unreached, which is a different count.
    assert np.all(np.isinf(distance[:4]))
    summary = mean_downslope_distance(distance, np.ones(16, dtype=bool))
    assert (summary.n_undefined, summary.n_unreachable, summary.n_reached) == (4, 4, 8)


def test_pit_keeps_an_infinite_distance() -> None:
    # A closed depression is never filled inside the operator: filling here
    # would hide an unconditioned surface behind a plausible number.
    vertices, connectivity = quad_mesh(5, 5, cell_size=RESOLUTION)
    reference = _plane(5, 5)
    reference[12] = -50.0  # cell (2, 2)
    metric = build_downslope_metric(reference, connectivity, vertices=vertices)

    target = np.zeros(25, dtype=bool)
    target[-5:] = True
    distance = downslope_distance_to_mask(metric, target)

    assert math.isinf(distance[12])
    assert math.isinf(distance[7])  # cell (1, 2), which drains into the pit
    assert distance[5] == pytest.approx(3.0 * RESOLUTION, rel=1e-12)


def test_target_mask_length_is_validated() -> None:
    vertices, connectivity = quad_mesh(2, 2, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(2, 2), connectivity, vertices=vertices)

    with pytest.raises(ValueError, match="target_mask must have 4 entries"):
        downslope_distance_to_mask(metric, np.ones(3, dtype=bool))


def test_metric_needs_vertices() -> None:
    _, connectivity = quad_mesh(2, 2, cell_size=RESOLUTION)
    with pytest.raises(ValueError, match="needs vertices"):
        build_downslope_metric(_plane(2, 2), connectivity, vertices=None)


def test_summary_splits_the_support_three_ways() -> None:
    distance = np.array([0.0, 5.0, np.inf, np.nan, 7.0])
    summary = mean_downslope_distance(distance, np.ones(5, dtype=bool))

    assert summary.n_support == 5
    assert (summary.n_reached, summary.n_unreachable, summary.n_undefined) == (3, 1, 1)
    assert math.isinf(summary.mean_m)
    assert math.isinf(summary.max_m)


def test_cap_replaces_unreachable_paths() -> None:
    distance = np.array([0.0, 5.0, np.inf, np.nan, 7.0])
    summary = mean_downslope_distance(distance, np.ones(5, dtype=bool), saturation_cap_m=10.0)

    assert summary.mean_m == pytest.approx((0.0 + 5.0 + 10.0 + 7.0) / 4.0, rel=1e-12)
    assert summary.max_m == pytest.approx(10.0, rel=1e-12)
    assert summary.n_unreachable == 1


def test_area_weighting_differs_from_cell_weighting() -> None:
    distance = np.array([0.0, 100.0])
    support = np.ones(2, dtype=bool)

    by_cell = mean_downslope_distance(distance, support)
    by_area = mean_downslope_distance(distance, support, weights=np.array([1.0, 3.0]))

    assert by_cell.mean_m == pytest.approx(50.0, rel=1e-12)
    assert by_area.mean_m == pytest.approx(75.0, rel=1e-12)


def test_empty_support_is_not_a_number() -> None:
    summary = mean_downslope_distance(np.array([1.0, 2.0]), np.zeros(2, dtype=bool))

    assert math.isnan(summary.mean_m)
    assert math.isnan(summary.max_m)
    assert summary.n_support == 0


def test_weight_length_is_validated_even_on_an_empty_support() -> None:
    with pytest.raises(ValueError, match="weights must have 2 entries"):
        mean_downslope_distance(np.array([1.0, 2.0]), np.zeros(2, dtype=bool), weights=np.ones(3))


def test_non_positive_weight_is_rejected() -> None:
    distance = np.array([1.0, np.inf])
    with pytest.raises(ValueError, match="finite and strictly positive"):
        mean_downslope_distance(distance, np.ones(2, dtype=bool), weights=np.array([1.0, 0.0]))


def test_longest_descent_length_is_the_catchment_cap() -> None:
    size = 6
    vertices, connectivity = quad_mesh(size, size, cell_size=RESOLUTION)
    metric = build_downslope_metric(_diagonal_plane(size), connectivity, vertices=vertices)
    outlet = np.zeros(size * size, dtype=bool)
    outlet[-1] = True

    assert longest_descent_length(metric, outlet) == pytest.approx(
        2.0 * RESOLUTION * (size - 1), rel=1e-12
    )


def test_longest_descent_length_rejects_an_empty_outlet() -> None:
    vertices, connectivity = quad_mesh(3, 3, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(3, 3), connectivity, vertices=vertices)

    with pytest.raises(ValueError, match="no cell descends to the outlet"):
        longest_descent_length(metric, np.zeros(9, dtype=bool))
