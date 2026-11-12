from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.catchment.drainage.distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
    mean_downslope_distance,
    shared_node_adjacency,
)
from tests._helpers.tolerances import tol
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    LENGTH_SCALE,
    N_CELLS,
    N_COLS,
    N_ROWS,
    analytic_receiver,
    build_bench,
    cell_id,
    crossing_thresholds,
    downstream_closure,
    interpolate_at,
    observed_network,
    sweep_distances,
)

# Unit tests for the downslope topographic distance operator.

RESOLUTION = 10.0
D4_OVER_D8 = tol("length_ratio_on_a_pure_diagonal_descent")


def _plane(nrow: int, ncol: int) -> np.ndarray:
    """Surface dropping one meter per row, draining to the south."""
    rows = np.arange(nrow, dtype="float64")[:, None]
    return np.broadcast_to(100.0 - rows, (nrow, ncol)).reshape(-1).copy()


def _diagonal_plane(size: int) -> np.ndarray:
    """Surface dropping one meter to the east and one to the south."""
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


def test_structured_grid_diagonal_descent_length() -> None:
    size = 6
    vertices, connectivity = quad_mesh(size, size, cell_size=RESOLUTION)
    reference = _diagonal_plane(size)
    target = np.zeros(size * size, dtype=bool)
    target[-1] = True  # the south-east corner

    shared_edge = build_downslope_metric(
        reference, connectivity, vertices=vertices, diagonal_neighbors=False
    )
    shared_node = build_downslope_metric(
        reference, connectivity, vertices=vertices, diagonal_neighbors=True
    )
    d4 = downslope_distance_to_mask(shared_edge, target)
    d8 = downslope_distance_to_mask(shared_node, target)

    assert d4[0] == pytest.approx(2.0 * RESOLUTION * (size - 1), rel=1e-12)
    assert d8[0] == pytest.approx(math.sqrt(2.0) * RESOLUTION * (size - 1), rel=1e-12)
    assert d4[0] / d8[0] == pytest.approx(D4_OVER_D8, rel=1e-5)


def _two_triangles() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        dtype="float64",
    )
    return vertices, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)


def test_the_shared_node_graph_itself_refuses_a_non_quad_mesh() -> None:
    _, triangles = _two_triangles()

    with pytest.raises(ValueError, match="structured quad mesh"):
        shared_node_adjacency(triangles, n_cells=2)


def test_the_descent_is_d8_by_default_as_in_the_paper() -> None:
    size = 6
    vertices, connectivity = quad_mesh(size, size, cell_size=RESOLUTION)
    target = np.zeros(size * size, dtype=bool)
    target[-1] = True

    metric = build_downslope_metric(_diagonal_plane(size), connectivity, vertices=vertices)

    assert metric.diagonal_neighbors is True
    distance = downslope_distance_to_mask(metric, target)
    assert distance[0] == pytest.approx(math.sqrt(2.0) * RESOLUTION * (size - 1), rel=1e-12)


def test_distance_is_not_symmetric() -> None:
    vertices, connectivity = quad_mesh(4, 1, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(4, 1), connectivity, vertices=vertices)

    upstream = np.array([True, False, False, False])
    downstream = np.array([False, False, False, True])
    to_downstream = downslope_distance_to_mask(metric, downstream)
    to_upstream = downslope_distance_to_mask(metric, upstream)

    assert to_downstream[0] == pytest.approx(3.0 * RESOLUTION, rel=1e-12)
    assert math.isinf(to_upstream[3])


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
    outlet = np.zeros(size * size, dtype=bool)
    outlet[-1] = True
    d4 = build_downslope_metric(
        _diagonal_plane(size), connectivity, vertices=vertices, diagonal_neighbors=False
    )
    d8 = build_downslope_metric(
        _diagonal_plane(size), connectivity, vertices=vertices, diagonal_neighbors=True
    )

    assert longest_descent_length(d4, outlet) == pytest.approx(
        2.0 * RESOLUTION * (size - 1), rel=1e-12
    )
    # Under D8 the longest descent is the diagonal, sqrt(2) cells per step:
    # the cap shortens with the graph, so it stays the longest finite path.
    assert longest_descent_length(d8, outlet) == pytest.approx(
        math.sqrt(2.0) * RESOLUTION * (size - 1), rel=1e-12
    )


def test_longest_descent_length_rejects_an_empty_outlet() -> None:
    vertices, connectivity = quad_mesh(3, 3, cell_size=RESOLUTION)
    metric = build_downslope_metric(_plane(3, 3), connectivity, vertices=vertices)

    with pytest.raises(ValueError, match="no cell descends to the outlet"):
        longest_descent_length(metric, np.zeros(9, dtype=bool))


def _uneven_row() -> tuple[np.ndarray, np.ndarray]:
    """One row of three quads, the last one four times wider than the others.

    Vertex means: (5, 5), (15, 5), (40, 5). The middle cell therefore sits
    10 m from its left neighbor and 25 m from its right one, so a drop that
    is larger to the right can still lose on slope.
    """
    xs = [0.0, 10.0, 20.0, 60.0]
    vertices = np.asarray(
        [(x, y) for y in (0.0, 10.0) for x in xs],
        dtype=float,
    )
    connectivity = np.asarray(
        [[col, col + 1, col + 5, col + 4] for col in range(3)],
        dtype=int,
    )
    return vertices, connectivity


def test_the_receiver_is_chosen_on_the_points_the_surface_was_sampled_at() -> None:
    vertices, connectivity = _uneven_row()
    # Middle cell: drop 6 m over 10 m to the left, drop 10 m over 25 m to the
    # right. On slope the left wins, on drop alone the right would.
    surface = np.asarray([4.0, 10.0, 0.0])

    by_polygon = build_downslope_metric(surface, connectivity, vertices=vertices)
    assert int(by_polygon.graph.downstream[1]) == 0
    assert by_polygon.edge_length[1] == pytest.approx(10.0)

    # Same mesh, same surface, but the values were sampled at centers that put
    # the right neighbor 3 m away: the slope to the right is now the steepest.
    seeds = np.asarray([(5.0, 5.0), (15.0, 5.0), (18.0, 5.0)])
    by_seed = build_downslope_metric(surface, connectivity, vertices=vertices, centroids=seeds)
    assert int(by_seed.graph.downstream[1]) == 2
    assert by_seed.edge_length[1] == pytest.approx(3.0)


def test_centroids_of_the_wrong_shape_are_refused_by_name() -> None:
    vertices, connectivity = _uneven_row()
    surface = np.asarray([4.0, 10.0, 0.0])
    with pytest.raises(ValueError, match="centroids must be"):
        build_downslope_metric(surface, connectivity, vertices=vertices, centroids=np.zeros((3, 3)))
    with pytest.raises(ValueError, match="centres but the surface has"):
        build_downslope_metric(surface, connectivity, vertices=vertices, centroids=np.zeros((2, 2)))


# The V-valley bench: which support the two mean distances are taken over.
#
# Four ways of combining a raw or downslope-closed network on each side, plus the
# one-cell outlet sealing. The bench decides between them without a DEM, without
# whitebox and without a solve, and it is the scientific non-regression guard on
# the choice the method makes: close the simulated network, keep the observed one
# raw, and add the outlet cell to the target of ``D_so`` only.

CLOSURE_IS_A_NO_OP = tol("v_valley_support_bench_case_a")
HOLE_DRIFT = tol("v_valley_support_bench_case_b")


# Measured on this bench. The support study reports the same structure on its
# own sweep grid, with roots within about 10 per cent of these.
ROOT_RAW_SIMULATED = 131.1
ROOT_CLOSED_SIMULATED = 190.4


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _only_root(d_so: np.ndarray, d_os: np.ndarray) -> float:
    roots = crossing_thresholds(d_so, d_os)
    assert len(roots) == 1, f"expected a single sign change, got {roots}"
    return roots[0]


def _r_optim(d_so: np.ndarray, d_os: np.ndarray, root: float) -> float:
    optimal = 0.5 * (interpolate_at(d_so, root) + interpolate_at(d_os, root))
    return optimal / LENGTH_SCALE


def test_bench_matches_the_analytic_receiver_graph(bench) -> None:
    graph = bench.metric.graph
    interior = [(row, col) for row in range(N_ROWS - 1) for col in range(N_COLS)]
    assert all(
        graph.downstream[cell_id(row, col)] == analytic_receiver(row, col) for row, col in interior
    )
    # The outlet is the only cell without a receiver, so no path is truncated
    # by a pit and every unreachable count below is about the target, not the
    # surface.
    assert np.flatnonzero(graph.downstream < 0).tolist() == [bench.outlet]
    assert np.nanmax(bench.drained_area) == pytest.approx(float(N_CELLS))


@pytest.mark.parametrize(
    ("case", "expected_alpha", "expected_reachable"),
    [
        ("aligned", 1.000, 1.000),
        ("hole", 0.980, 1.000),
        ("shifted", 0.505, 0.457),
        ("truncated", 0.878, 0.734),
    ],
)
def test_observed_variants_reproduce_the_published_diagnostics(
    bench, case: str, expected_alpha: float, expected_reachable: float
) -> None:
    observed = observed_network(case)
    alpha = observed.sum() / downstream_closure(bench, observed).sum()

    to_observed = downslope_distance_to_mask(bench.metric, observed)
    active = bench.metric.graph.active
    reachable = float(np.mean(np.isfinite(to_observed[active])))

    assert alpha == pytest.approx(expected_alpha, abs=5e-4)
    assert reachable == pytest.approx(expected_reachable, abs=5e-4)


def test_case_a_closing_the_observed_network_is_a_no_op(bench) -> None:
    # alpha = 1: the observed network already is its own downslope closure, so
    # closing it can only be a strict no-op. This is the direct proof that the
    # closure brings nothing on a well-registered network.
    observed = observed_network("aligned")

    raw_simulated_raw_observed = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=False, close_observed=False, seal_outlet=False
        )
    )
    raw_simulated_closed_observed = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=False, close_observed=True, seal_outlet=False
        )
    )
    closed_simulated_raw_observed = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=True, close_observed=False, seal_outlet=False
        )
    )
    closed_simulated_closed_observed = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=True, close_observed=True, seal_outlet=False
        )
    )
    sealed = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=True, close_observed=False, seal_outlet=True
        )
    )

    assert raw_simulated_closed_observed == pytest.approx(
        raw_simulated_raw_observed, rel=CLOSURE_IS_A_NO_OP
    )
    assert closed_simulated_closed_observed == pytest.approx(
        closed_simulated_raw_observed, rel=CLOSURE_IS_A_NO_OP
    )
    # Sealing an outlet that already belongs to the observed network changes
    # nothing either.
    assert sealed == pytest.approx(closed_simulated_raw_observed, rel=CLOSURE_IS_A_NO_OP)

    # Closing the simulated network, on the other hand, moves the root by a
    # factor of about 1.5: that choice is not cosmetic.
    assert raw_simulated_raw_observed == pytest.approx(ROOT_RAW_SIMULATED, rel=1e-3)
    assert closed_simulated_raw_observed == pytest.approx(ROOT_CLOSED_SIMULATED, rel=1e-3)


def test_case_b_a_rasterisation_hole_does_not_justify_closing(bench) -> None:
    # One missing cell in the middle of the observed network creates no
    # infinite distance: the path that crosses it meets the next cell down.
    observed = observed_network("hole")
    aligned = observed_network("aligned")

    with_hole = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=True, close_observed=False, seal_outlet=False
        )
    )
    without_hole = _only_root(
        *sweep_distances(
            bench, aligned, close_simulated=True, close_observed=False, seal_outlet=False
        )
    )
    drift = abs(with_hole - without_hole) / without_hole
    assert drift < HOLE_DRIFT

    # Closing the observed network hides the hole entirely, which is exactly
    # what makes it look attractive and exactly why it must not be done.
    hidden = _only_root(
        *sweep_distances(
            bench, observed, close_simulated=True, close_observed=True, seal_outlet=False
        )
    )
    assert hidden == pytest.approx(ROOT_CLOSED_SIMULATED, rel=1e-3)
    assert drift > 0.0


def test_lower_axis_cells_never_leave_the_catchment(bench) -> None:
    # A guard on the geometry the other tests rely on: the bottom row drains
    # laterally to the outlet, so no cell escapes through the southern edge.
    outlet_mask = np.zeros(N_CELLS, dtype=bool)
    outlet_mask[bench.outlet] = True
    to_outlet = downslope_distance_to_mask(bench.metric, outlet_mask)
    assert np.all(np.isfinite(to_outlet))
    assert to_outlet[cell_id(0, AXIS_COL)] == pytest.approx(600.0, rel=1e-12)
