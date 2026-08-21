"""The V-valley bench: which support the two mean distances are taken over.

Four ways of combining a raw or downslope-closed network on each side, plus the
one-cell outlet sealing. The bench decides between them without a DEM, without
whitebox and without a solve, and it is the scientific non-regression guard on
the choice the method makes: close the simulated network, keep the observed one
raw, and add the outlet cell to the target of ``D_so`` only.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.topographic_distance import (
    downslope_distance_to_mask,
    longest_descent_length,
    mean_downslope_distance,
)
from tests._helpers.tolerances import tol
from tests._helpers.v_valley import (
    AXIS_COL,
    LENGTH_SCALE,
    N_CELLS,
    N_COLS,
    N_ROWS,
    analytic_receiver,
    build_bench,
    cell_id,
    criterion_slope,
    crossing_thresholds,
    downstream_closure,
    interpolate_at,
    observed_network,
    simulated_network,
    sweep_distances,
)

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


def test_case_c_closing_the_observed_hides_a_misregistered_network(bench) -> None:
    # The observed network sits one column off the talweg. The method must
    # reject that case, and closing the observed network makes it pass.
    observed = observed_network("shifted")

    closed_observed = sweep_distances(
        bench, observed, close_simulated=True, close_observed=True, seal_outlet=False
    )
    sealed = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=True
    )

    hidden_root = _only_root(*closed_observed)
    honest_root = _only_root(*sealed)

    assert _r_optim(*closed_observed, hidden_root) < 2.0
    assert _r_optim(*sealed, honest_root) > 2.0
    assert honest_root > 10.0 * hidden_root


def test_case_c_raw_observed_needs_the_outlet_to_be_defined(bench) -> None:
    observed = observed_network("shifted")
    d_so, d_os = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=False
    )
    # Every cell west of the shifted network descends to the axis and never
    # meets it, so the criterion is undefined over the whole sweep.
    assert not np.any(np.isfinite(d_so - d_os))


def test_case_d_outlet_sealing_restores_the_root(bench) -> None:
    # The observed network stops six cells above the outlet. The simulated
    # network retracts towards that very reach as the threshold grows, so the
    # criterion loses its sign change at the high end of the bracket.
    observed = observed_network("truncated")

    unsealed = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=False
    )
    assert crossing_thresholds(*unsealed) == []

    sealed = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=True
    )
    root = _only_root(*sealed)
    assert np.isfinite(root)
    assert _r_optim(*sealed, root) < 2.0


def test_case_d_the_saturation_cap_does_not_replace_the_outlet(bench) -> None:
    # Capping unreachable paths is the policy the cost uses, and it must not be
    # mistaken for the repair: it keeps every point defined, and the sign change
    # is still missing.
    observed = observed_network("truncated")
    outlet_mask = np.zeros(N_CELLS, dtype=bool)
    outlet_mask[bench.outlet] = True
    cap = longest_descent_length(bench.metric, outlet_mask)

    d_so, d_os = sweep_distances(
        bench,
        observed,
        close_simulated=True,
        close_observed=False,
        seal_outlet=False,
        saturation_cap_m=cap,
    )
    defined = np.isfinite(d_so - d_os)
    assert defined.sum() >= d_so.size - 1  # only the empty-network point drops out
    assert crossing_thresholds(d_so, d_os) == []


def test_closing_the_simulated_network_lifts_the_observed_zero_fraction(bench) -> None:
    # More than two thirds of the observed network ends up at distance zero
    # once the simulated network is closed: the two networks share a trunk.
    observed = observed_network("aligned")
    d_so, d_os = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=True
    )
    root = _only_root(d_so, d_os)

    closed = downstream_closure(bench, simulated_network(bench, root))
    to_simulated = downslope_distance_to_mask(bench.metric, closed)
    zero_fraction = float(np.mean(to_simulated[observed] == 0.0))

    raw = simulated_network(bench, root)
    to_raw = downslope_distance_to_mask(bench.metric, raw)
    raw_zero_fraction = float(np.mean(to_raw[observed] == 0.0))

    assert zero_fraction > 0.70
    assert zero_fraction > raw_zero_fraction
    # The dilution does not make the support degenerate: the mean stays finite
    # and the counts still add up.
    summary = mean_downslope_distance(to_simulated, observed)
    assert summary.n_support == int(observed.sum())
    assert summary.n_reached == summary.n_support
    assert np.isfinite(summary.mean_m)


def test_closing_the_simulated_network_does_not_cost_sensitivity(bench) -> None:
    # Closing the simulated network drives most of the observed side to zero
    # distance, which looks like a loss of information. It is not: the criterion
    # gets steeper, because the closure makes D_os collapse faster once the
    # network is over-extended. Measured at +21 per cent here, +22 per cent in
    # the support study.
    observed = observed_network("aligned")
    raw = sweep_distances(
        bench, observed, close_simulated=False, close_observed=False, seal_outlet=True
    )
    closed = sweep_distances(
        bench, observed, close_simulated=True, close_observed=False, seal_outlet=True
    )

    raw_slope = criterion_slope(*raw, _only_root(*raw))
    closed_slope = criterion_slope(*closed, _only_root(*closed))
    assert closed_slope >= raw_slope


def test_lower_axis_cells_never_leave_the_catchment(bench) -> None:
    # A guard on the geometry the other tests rely on: the bottom row drains
    # laterally to the outlet, so no cell escapes through the southern edge.
    outlet_mask = np.zeros(N_CELLS, dtype=bool)
    outlet_mask[bench.outlet] = True
    to_outlet = downslope_distance_to_mask(bench.metric, outlet_mask)
    assert np.all(np.isfinite(to_outlet))
    assert to_outlet[cell_id(0, AXIS_COL)] == pytest.approx(600.0, rel=1e-12)
