"""The signed-gap cost of a simulated stream network against a mapped one (distances in m).

D_so descends from the simulated network onto the mapped one, D_os the other
way. The cost is their signed gap, capped by the longest descent of the
catchment. Cases run on the V-valley bench and on a diagonal valley.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.calibration.criteria.hydrographic_network_distance import distance_mean
from hydromodpy.catchment.drainage.distance import (
    downslope_distance_to_mask,
    longest_descent_length,
)
from hydromodpy.catchment.stream_network.cost import (
    DISTANCE_METHOD,
    SeepageDistanceResult,
    secondary_diagnostics,
    seepage_distance_cost,
    weighted_pair,
)
from hydromodpy.catchment.stream_network.geometry import (
    CriterionSupports,
    build_network_geometry,
)
from hydromodpy.catchment.stream_network.network import (
    SimulatedNetwork,
    build_simulated_network,
    downstream_closure,
)
from hydromodpy.mesh.cells.crossed_by_lines import line_crossing_cell_mask
from hydromodpy.mesh.cells.in_polygons import vector_cell_mask
from hydromodpy.mesh.planar.geometry import cell_polygons
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    LENGTH_SCALE,
    N_CELLS,
    N_COLS,
    N_ROWS,
    THRESHOLDS,
    build_bench,
    cell_id,
    observed_network,
    simulated_network,
)

# A mapped network that is exactly the simulated one scores J = 0.
#
# The criterion's zero is the equality of D_so and D_os. If the map is the
# polyline through the centers of a simulated chain, that equality must hold, or
# the search moves K on a perfect match. The crossing rule gives the chain back
# cell for cell, in D8 along a diagonal talweg. The touch rule adds, at every
# diagonal step, the two cells that share the corner: D_so stays at zero, D_os
# grows, J_signed turns negative and the search pulls K down. That
# counter-example is the reason ``crossing`` is the default.


CRS = "EPSG:2154"
N = 24
CELL = 75.0
FIRST_SEEPING_ROW = 6


def _diagonal_valley():
    """A V valley whose talweg runs down the grid diagonal to cell (0, 0)."""
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = (100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)).reshape(-1)
    centres = np.column_stack([(cols.ravel() + 0.5) * CELL, (rows.ravel() + 0.5) * CELL])
    return vertices, connectivity, top, centres


def _signed_gap(rule: str) -> tuple[np.ndarray, np.ndarray, dict]:
    vertices, connectivity, top, centres = _diagonal_valley()
    n_cells = top.size
    area = np.full(n_cells, CELL * CELL)
    talweg = np.zeros(n_cells, dtype=bool)
    talweg[[k * N + k for k in range(FIRST_SEEPING_ROW, N)]] = True

    def geometry(observed: np.ndarray):
        return build_network_geometry(
            topography=top,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed,
            cell_area_m2=area,
            cell_centroids=centres,
            mean_recharge_m_s=1.0e-8,
            tau_specific_ratio=0.0,
            diagonal_neighbors=True,
        )

    chain = downstream_closure(geometry(talweg).metric, talweg)
    ordered = sorted(np.flatnonzero(chain), key=lambda cell: divmod(int(cell), N))
    mapped = [LineString(centres[ordered])]
    polygons = cell_polygons(vertices, connectivity)
    if rule == "crossing":
        observed = line_crossing_cell_mask(
            polygons, vertices, connectivity, centres, mapped, mesh_crs=CRS, geometry_crs=CRS
        ).mask
    else:
        observed = vector_cell_mask(polygons, mapped, mesh_crs=CRS, geometry_crs=CRS)

    geo = geometry(observed)
    simulated = SimulatedNetwork(seepage=talweg, network=chain, threshold_m3_s=np.zeros(n_cells))
    result = seepage_distance_cost(
        simulated=simulated,
        observed=geo.observed,
        outlet=geo.outlet,
        catchment=geo.catchment,
        metric=geo.metric,
        distance_to_observed=geo.distance_to_observed,
        distance_to_observed_raw=geo.distance_to_observed_raw,
        cell_area_m2=area,
        length_scale_m=geo.h_obs_m,
        saturation_cap_m=geo.saturation_cap_m,
    )
    return chain, np.asarray(observed, dtype=bool), result.components


def test_crossing_rule_scores_zero() -> None:
    chain, observed, components = _signed_gap("crossing")

    assert np.array_equal(observed, chain)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] == pytest.approx(0.0, abs=1e-9)
    assert components["J_signed"] == pytest.approx(0.0, abs=1e-9)


def test_touch_rule_turns_a_perfect_match_negative() -> None:
    chain, observed, components = _signed_gap("touch")

    assert int(observed.sum()) == int(chain.sum()) + 2 * (int(chain.sum()) - 1)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] > 0.0
    assert components["J_signed"] < 0.0


# ``distance_mean`` of an empty simulated network is NaN, not a negative cost.
#
# The pair of an empty network rebuilds ``D_so`` from the residual,
# ``D_os - L_cap``, so ``distance_gap`` still reads ``L_cap``. Summed as
# ``(D_so + D_os) / 2`` the same pair gave a negative cost, below every real
# network: -1300 m for ``D_os = 1200`` and ``L_cap = 5000``.


CAP = 5000.0


def _empty(d_os: float = 1200.0) -> SeepageDistanceResult:
    return SeepageDistanceResult(
        signed_gap=-CAP, status="empty_network", components={"D_os": d_os, "D_so": math.nan}
    )


def _real(d_so: float, d_os: float) -> SeepageDistanceResult:
    return SeepageDistanceResult(
        signed_gap=d_so - d_os, status="ok", components={"D_os": d_os, "D_so": d_so}
    )


def test_empty_network_has_no_mean_distance() -> None:
    assert math.isnan(distance_mean(weighted_pair(_empty())))


def test_network_on_the_map_scores_zero() -> None:
    assert distance_mean(weighted_pair(_real(0.0, 0.0))) == 0.0


# The signed gap criterion, on the V-valley bench.
#
# The bench is the same one the support study runs, so the cost function is
# driven here exactly as a calibration drives it: a sweep over a threshold
# standing in for ``K/R``, and the residual read at each point.


@pytest.fixture(scope="module")
def bench():
    return build_bench()


@pytest.fixture(scope="module")
def geometry(bench):
    """The static half a calibration computes once and reuses at every trial."""
    outlet_mask = np.zeros(N_CELLS, dtype=bool)
    outlet_mask[bench.outlet] = True
    to_outlet = downslope_distance_to_mask(bench.metric, outlet_mask)
    catchment = np.isfinite(to_outlet) & bench.metric.graph.active
    return {
        "outlet": bench.outlet,
        "catchment": catchment,
        "cap": longest_descent_length(bench.metric, outlet_mask),
        "areas": np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
    }


def _network_from_threshold(bench, threshold: float):
    """Build a simulated network from the bench pattern, through the real path."""
    pattern = simulated_network(bench, float(threshold))
    flux = np.where(pattern, 1.0, 0.0)
    return build_simulated_network(
        flux,
        threshold_m3_s=np.full(N_CELLS, 0.5),
        metric=bench.metric,
    )


def _evaluate(bench, geometry, observed, threshold, **kwargs):
    sealed = observed.copy()
    sealed[geometry["outlet"]] = True
    return seepage_distance_cost(
        simulated=_network_from_threshold(bench, threshold),
        observed=observed,
        outlet=geometry["outlet"],
        catchment=geometry["catchment"],
        metric=bench.metric,
        distance_to_observed=downslope_distance_to_mask(bench.metric, sealed),
        distance_to_observed_raw=downslope_distance_to_mask(bench.metric, observed),
        cell_area_m2=geometry["areas"],
        length_scale_m=LENGTH_SCALE,
        saturation_cap_m=geometry["cap"],
        **kwargs,
    )


def test_residual_changes_sign_once_over_the_sweep(bench, geometry) -> None:
    # Without a sign change there is no root to bracket and a bisection is meaningless.
    observed = observed_network("aligned")
    gaps = []
    for threshold in THRESHOLDS:
        result = _evaluate(bench, geometry, observed, threshold)
        gaps.append(result.signed_gap if result.status != "failed" else np.nan)
    gaps = np.asarray(gaps)
    defined = np.isfinite(gaps)
    signs = np.sign(gaps[defined])
    crossings = int(np.count_nonzero(np.diff(signs) != 0))

    assert crossings == 1, gaps[defined]
    assert gaps[defined][0] > 0.0
    assert gaps[defined][-1] < 0.0


def test_cost_is_the_absolute_residual(bench, geometry) -> None:
    result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
    assert result.components["J"] == pytest.approx(abs(result.signed_gap))
    assert result.components["J_signed"] == pytest.approx(result.signed_gap)


def test_result_fields() -> None:
    # The optimizer reads the components; a second copy of J and D_optim on
    # the dataclass was read by nothing.
    assert set(SeepageDistanceResult.__dataclass_fields__) == {
        "signed_gap",
        "status",
        "components",
    }


def test_distance_method_name() -> None:
    assert DISTANCE_METHOD == "downslope_simclosed_obsraw_outletsealed"


def test_empty_network_is_the_high_end_of_the_bracket(bench, geometry) -> None:
    # No network at all must give a defined, negative residual: a large
    # positive penalty would destroy the sign structure a bracket needs.
    result = _evaluate(bench, geometry, observed_network("aligned"), float(N_CELLS) * 10.0)
    assert result.status == "empty_network"
    assert result.signed_gap == pytest.approx(-geometry["cap"])
    assert np.isnan(result.components["D_so"])


# D_so descends onto the mapped network, which does not move over the search, so
# a cell that never arrives there is a depression left in the routing surface.
# D_os descends onto the simulated network, which the search retracts on purpose
# at the high end of its bracket, so a cell that never arrives there says the
# model has no stream below it. Both shares are published and neither refuses a trial.
LAST_SIMULATED_ROW = 40


def _truncated_network() -> SimulatedNetwork:
    """The valley axis from the first mapped row down to row 40, short of the outlet."""
    mask = np.zeros(N_CELLS, dtype=bool)
    for row in range(FIRST_OBSERVED_ROW, LAST_SIMULATED_ROW + 1):
        mask[cell_id(row, AXIS_COL)] = True
    return SimulatedNetwork(seepage=mask, network=mask, threshold_m3_s=np.zeros(N_CELLS))


def _evaluate_truncated(bench, geometry, distance_to_observed):
    observed = observed_network("aligned")
    return seepage_distance_cost(
        simulated=_truncated_network(),
        observed=observed,
        outlet=geometry["outlet"],
        catchment=geometry["catchment"],
        metric=bench.metric,
        distance_to_observed=distance_to_observed,
        distance_to_observed_raw=downslope_distance_to_mask(bench.metric, observed),
        cell_area_m2=geometry["areas"],
        length_scale_m=LENGTH_SCALE,
        saturation_cap_m=geometry["cap"],
    )


def test_unreachable_mapped_cells_leave_the_trial_standing(bench, geometry) -> None:
    # Water runs south, so the mapped cells below the last simulated one have
    # nothing downstream to descend into: unreachable, far past the 5 % bound.
    sealed = observed_network("aligned").copy()
    sealed[geometry["outlet"]] = True
    result = _evaluate_truncated(bench, geometry, downslope_distance_to_mask(bench.metric, sealed))

    assert result.components["n_unreachable_os"] == pytest.approx(
        float(N_ROWS - 1 - LAST_SIMULATED_ROW)
    )
    assert result.components["frac_unreachable_os"] > 0.05
    assert result.components["frac_unreachable_so"] == 0.0
    assert result.status == "ok"


def test_unreachable_simulated_cells_are_a_reported_share(bench, geometry) -> None:
    # The same trial with the descent to the mapped network taken away. A geometry
    # cannot produce this, the outlet being sealed into the target, so no status
    # says it: the share is the whole record of it.
    result = _evaluate_truncated(bench, geometry, np.full(N_CELLS, np.inf))

    assert result.components["frac_unreachable_so"] == pytest.approx(1.0)
    assert result.status == "ok"


def test_water_bodies_leave_the_supports_but_stay_in_the_graph(bench, geometry) -> None:
    observed = observed_network("aligned")
    lake = np.zeros(N_CELLS, dtype=bool)
    lake[[cell_id(row, 20) for row in range(40, 45)]] = True

    without = _evaluate(bench, geometry, observed, 200.0)
    with_lake = _evaluate(bench, geometry, observed, 200.0, excluded=lake)

    assert with_lake.components["n_network_obs"] < without.components["n_network_obs"]
    # The upslope cells still descend through the reservoir, so nothing
    # becomes unreachable by excluding it from the supports.
    assert with_lake.components["frac_unreachable_so"] == pytest.approx(
        without.components["frac_unreachable_so"], abs=1e-9
    )


def test_no_excluded_cells_changes_nothing(bench, geometry) -> None:
    observed = observed_network("aligned")
    without = _evaluate(bench, geometry, observed, 200.0)
    with_none = _evaluate(bench, geometry, observed, 200.0, excluded=None)
    assert with_none.signed_gap == pytest.approx(without.signed_gap)


def test_both_weightings_are_reported(bench, geometry) -> None:
    result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
    for key in ("D_so_cell", "D_so_area", "D_os_cell", "D_os_area"):
        assert np.isfinite(result.components[key])
    # On a uniform mesh the two conventions coincide; their gap is what
    # measures the effect of a refinement.
    assert result.components["D_so_cell"] == pytest.approx(result.components["D_so_area"])


# The secondary diagnostics other codes of the method recorded.
#
# ``D_so / D_os`` is the ratio the v1 example 10 kept as ``DSO/DOS`` and the
# authors' dichotomy branched on. The overlap indices are ``fuzzy`` and
# ``total_length`` of the authors' published code (Zenodo 8311547,
# ``objective_function.py``). All of them are components, never the cost.


# Ten cells in the catchment, one outside it. Four cells of each area 100 m2
# are simulated, three are mapped, two of them in common.
KEEP = np.array([True] * 10 + [False])
SIMULATED = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1], dtype=bool)
MAPPED = np.array([0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0], dtype=bool)
AREAS = np.full(11, 100.0)


def _supports() -> CriterionSupports:
    support_so = SIMULATED & KEEP
    support_os = MAPPED & KEEP
    return CriterionSupports(
        keep=KEEP,
        support_so=support_so,
        support_os=support_os,
        valid=support_so & MAPPED,
        excess=support_so & ~MAPPED,
        missing=support_os & ~SIMULATED,
        seepage=support_so,
    )


def test_overlap_indices() -> None:
    out = secondary_diagnostics(d_so=30.0, d_os=20.0, supports=_supports(), cell_area_m2=AREAS)

    # So = 3, Sm = 4, Si = 2, Ni = 1, Nc = 5, No = 10 - 3 = 7.
    ea = 1.0 - abs(4.0 - 3.0) / 3.0
    sa = 1.0 - 2.0 / 3.0
    na = 1.0 - 1.0 / 7.0
    assert out["n_neither"] == 5.0
    assert out["overlap_Ea"] == pytest.approx(ea)
    assert out["overlap_Sa"] == pytest.approx(sa)
    assert out["overlap_Na"] == pytest.approx(na)
    assert out["overlap_E"] == pytest.approx(ea * sa * na)
    assert out["D_so_over_D_os"] == pytest.approx(1.5)


def test_length_on_the_scored_support() -> None:
    out = secondary_diagnostics(d_so=1.0, d_os=1.0, supports=_supports(), cell_area_m2=AREAS)

    # The simulated cell outside the catchment is not counted.
    assert out["L_sim_m"] == pytest.approx(40.0)
    assert out["L_obs_m"] == pytest.approx(30.0)


def test_refusals(bench, geometry) -> None:
    with pytest.raises(ValueError, match="holds no cell inside the catchment"):
        _evaluate(bench, geometry, np.zeros(N_CELLS, dtype=bool), 200.0)
