"""Tests of `metrics.downslope_network`."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

import hydromodpy
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    HydrographicNetworkDistance,
    distance_gap,
    distance_mean,
)
from hydromodpy.calibration.metrics.downslope_network import (
    DISTANCE_METHOD,
    SeepageDistanceResult,
    secondary_diagnostics,
    seepage_distance_cost,
    weighted_pair,
)
from hydromodpy.calibration.observations.observed_network import water_body_mask
from hydromodpy.mesh.cells.crossed_by_lines import line_crossing_cell_mask
from hydromodpy.mesh.cells.in_polygons import vector_cell_mask
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.results.derive.stream import geometry as stream_geometry
from hydromodpy.results.derive.stream.geometry import (
    CriterionSupports,
    build_network_geometry,
    criterion_supports,
    recharge_session,
)
from hydromodpy.results.derive.stream.network import (
    SimulatedNetwork,
    build_simulated_network,
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.spatial.drainage.distance import downslope_distance_to_mask, longest_descent_length
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
    cell_id,
    observed_network,
    simulated_network,
)

# From test_a_map_drawn_from_the_model_scores_zero.py
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


def test_the_simulated_chain_follows_the_diagonal() -> None:
    chain, _, _ = _signed_gap("crossing")

    assert np.flatnonzero(chain).tolist() == [k * N + k for k in range(N)]


def test_the_crossing_rule_gives_the_chain_back_and_scores_zero() -> None:
    chain, observed, components = _signed_gap("crossing")

    assert np.array_equal(observed, chain)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] == pytest.approx(0.0, abs=1e-9)
    assert components["J_signed"] == pytest.approx(0.0, abs=1e-9)


def test_the_touch_rule_turns_a_perfect_match_negative() -> None:
    chain, observed, components = _signed_gap("touch")

    assert int(observed.sum()) == int(chain.sum()) + 2 * (int(chain.sum()) - 1)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] > 0.0
    assert components["J_signed"] < 0.0


# From test_distance_mean_of_an_empty_network_is_undefined.py
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


def test_an_empty_network_has_no_mean_distance() -> None:
    assert math.isnan(distance_mean(weighted_pair(_empty())))


def test_one_empty_bound_of_two_makes_the_mean_undefined() -> None:
    pairs = weighted_pair(_real(2000.0, 1200.0), 0.5) + weighted_pair(_empty(), 0.5)

    assert math.isnan(distance_mean(pairs))


def test_the_gap_of_an_empty_network_is_still_the_cap() -> None:
    assert distance_gap(weighted_pair(_empty())) == CAP


def test_a_real_network_keeps_its_mean() -> None:
    assert distance_mean(weighted_pair(_real(2000.0, 1200.0))) == 1600.0


def test_a_network_lying_on_the_map_scores_zero_not_nan() -> None:
    assert distance_mean(weighted_pair(_real(0.0, 0.0))) == 0.0


def test_the_criterion_returns_nan_for_an_empty_network() -> None:
    result = HydrographicNetworkDistance("distance_mean").score(weighted_pair(_empty()))

    assert math.isnan(result.cost)


# From test_downslope_network_cost.py
# The signed gap criterion, on the V-valley bench.
#
# The bench is the same one the support study runs, so the cost function is
# driven here exactly as a calibration drives it: a sweep over a threshold
# standing in for ``K/R``, and the residual read at each point.


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


def _divided_valley(first_row: int) -> np.ndarray:
    """The V valley with a divide between ``first_row - 1`` and ``first_row``.

    The rows above the divide slope north and leave the domain through its
    northern border; the rows below keep the valley and its southern outlet.
    The catchment of that outlet on the graph is therefore rows ``first_row``
    and below, and the rows above are a buffer that does not drain into it.
    """
    rows = np.arange(N_ROWS, dtype=float)[:, None]
    cols = np.arange(N_COLS, dtype=float)[None, :]
    divide = float(first_row) - 0.5
    return (1000.0 - np.abs(rows - divide) + 2.0 * np.abs(cols - AXIS_COL)).reshape(-1)


def _rows_from(first_row: int) -> np.ndarray:
    """Every cell of the rows ``first_row`` and below."""
    mask = np.zeros(N_CELLS, dtype=bool)
    for row in range(first_row, N_ROWS):
        for col in range(N_COLS):
            mask[cell_id(row, col)] = True
    return mask


class TestSimulatedNetwork:
    def test_the_threshold_is_strict(self, bench) -> None:
        flux = np.array([0.0, 1.0, 2.0] + [0.0] * (N_CELLS - 3))
        network = build_simulated_network(
            flux, threshold_m3_s=np.full(N_CELLS, 1.0), metric=bench.metric
        )
        # A cell releasing exactly its threshold is not a stream.
        assert not network.seepage[1]
        assert network.seepage[2]

    def test_the_network_is_the_closure_of_the_seepage(self, bench) -> None:
        network = _network_from_threshold(bench, 200.0)
        assert np.array_equal(network.network, downstream_closure(bench.metric, network.seepage))
        assert network.n_network >= network.n_seepage
        assert 0.0 < network.continuity <= 1.0

    def test_a_transient_stack_is_read_at_its_last_state(self, bench) -> None:
        stack = np.zeros((3, N_CELLS))
        stack[0, 5] = 10.0
        stack[-1, 7] = 10.0
        network = build_simulated_network(
            stack, threshold_m3_s=np.zeros(N_CELLS), metric=bench.metric
        )
        assert network.seepage[7]
        assert not network.seepage[5]

    def test_a_mismatched_cell_count_is_refused(self, bench) -> None:
        with pytest.raises(ValueError, match="the mesh holds"):
            build_simulated_network(np.zeros(7), threshold_m3_s=np.zeros(7), metric=bench.metric)


class TestSpecificThreshold:
    def test_it_scales_with_the_cell_area(self) -> None:
        threshold = specific_seepage_threshold(np.array([100.0, 900.0]), 1e-8, ratio=1e-4)
        # A cell nine times larger carries a threshold nine times larger, so the
        # mask follows the physics rather than the mesh refinement.
        assert threshold[1] / threshold[0] == pytest.approx(9.0)

    def test_a_zero_ratio_reproduces_the_paper(self) -> None:
        threshold = specific_seepage_threshold(np.array([100.0]), 1e-8, ratio=0.0)
        assert threshold.tolist() == [0.0]

    def test_a_negative_ratio_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            specific_seepage_threshold(np.array([1.0]), 1e-8, ratio=-1.0)


class TestSignedGap:
    def test_the_residual_changes_sign_once_over_the_sweep(self, bench, geometry) -> None:
        """The check the whole method rests on: without a sign change there is
        no root to bracket and a bisection would be meaningless here."""
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

    def test_the_cost_is_the_absolute_residual(self, bench, geometry) -> None:
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        assert result.components["J"] == pytest.approx(abs(result.signed_gap))
        assert result.components["J_signed"] == pytest.approx(result.signed_gap)

    def test_the_result_carries_no_field_the_optimizer_does_not_read(self) -> None:
        # The optimizer reads the components; a second copy of J and D_optim on
        # the dataclass was read by nothing and its docstring claimed otherwise.
        assert set(SeepageDistanceResult.__dataclass_fields__) == {
            "signed_gap",
            "status",
            "components",
        }

    def test_an_empty_network_is_the_high_end_of_the_bracket(self, bench, geometry) -> None:
        # No network at all must give a defined, negative residual: a large
        # positive penalty would destroy the sign structure a bracket needs.
        result = _evaluate(bench, geometry, observed_network("aligned"), float(N_CELLS) * 10.0)
        assert result.status == "empty_network"
        assert result.signed_gap == pytest.approx(-geometry["cap"])
        assert np.isnan(result.components["D_so"])


class TestValidityCriterion:
    def test_a_misregistered_network_is_rejected(self, bench, geometry) -> None:
        """The scientific non-regression: a network one column off the talweg
        must fail Eq. 4, which is exactly the signal closing the observed
        network erases."""
        observed = observed_network("shifted")
        rejected = [_evaluate(bench, geometry, observed, threshold) for threshold in THRESHOLDS]
        r_optim = [r.components["r_optim"] for r in rejected if r.status == "ok"]
        assert r_optim, "the shifted case produced no evaluable point"
        assert max(r_optim) > 2.0

    def test_an_aligned_network_stays_inside_the_validity_bound(self, bench, geometry) -> None:
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        assert result.components["r_optim"] < 2.0
        assert result.components["r_optim_valid"] == 1.0


class TestTheUnreachableSharesAreReportedAndBoundNothing:
    """Both shares are published, and neither refuses a trial.

    The two directions do not mean the same thing. ``D_so`` descends onto the
    mapped network, which does not move over the search, so a cell that never
    arrives there is a depression left in the routing surface. ``D_os`` descends
    onto the SIMULATED network, which the search retracts on purpose at the high
    end of its bracket, so a cell that never arrives there is the measurement
    saying the model has no stream below it.
    """

    LAST_SIMULATED_ROW = 40

    def _truncated_network(self) -> SimulatedNetwork:
        """The valley axis down to one row, stopping well short of the outlet."""
        mask = np.zeros(N_CELLS, dtype=bool)
        for row in range(FIRST_OBSERVED_ROW, self.LAST_SIMULATED_ROW + 1):
            mask[cell_id(row, AXIS_COL)] = True
        return SimulatedNetwork(seepage=mask, network=mask, threshold_m3_s=np.zeros(N_CELLS))

    def _evaluate(self, bench, geometry, simulated, distance_to_observed):
        observed = observed_network("aligned")
        return seepage_distance_cost(
            simulated=simulated,
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

    def test_a_mapped_support_that_cannot_descend_leaves_the_trial_standing(
        self, bench, geometry
    ) -> None:
        # Water runs south, so the twenty mapped cells below the last simulated
        # one have nothing downstream to descend into: unreachable by
        # construction, and far past the five per cent bound.
        simulated = self._truncated_network()
        sealed = observed_network("aligned").copy()
        sealed[geometry["outlet"]] = True
        result = self._evaluate(
            bench, geometry, simulated, downslope_distance_to_mask(bench.metric, sealed)
        )

        assert result.components["n_unreachable_os"] == pytest.approx(
            float(N_ROWS - 1 - self.LAST_SIMULATED_ROW)
        )
        assert result.components["frac_unreachable_os"] > 0.05
        assert result.components["frac_unreachable_so"] == 0.0
        assert result.status == "ok"

    def test_a_simulated_support_that_cannot_descend_is_a_reported_share(
        self, bench, geometry
    ) -> None:
        # The same trial, with the descent to the mapped network taken away. A
        # geometry cannot produce this, the outlet being sealed into the target, so
        # no status says it: the share is the whole record of it.
        result = self._evaluate(
            bench, geometry, self._truncated_network(), np.full(N_CELLS, np.inf)
        )

        assert result.components["frac_unreachable_so"] == pytest.approx(1.0)
        assert result.status == "ok"


class TestSupportsAndDiagnostics:
    def test_water_bodies_leave_the_supports_but_stay_in_the_graph(self, bench, geometry) -> None:
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

    def test_both_weightings_are_always_reported(self, bench, geometry) -> None:
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        for key in ("D_so_cell", "D_so_area", "D_os_cell", "D_os_area"):
            assert np.isfinite(result.components[key])
        # On a uniform mesh the two conventions coincide; their gap is what
        # measures the effect of a refinement.
        assert result.components["D_so_cell"] == pytest.approx(result.components["D_so_area"])

    def test_the_confusion_counts_add_up(self, bench, geometry) -> None:
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        components = result.components
        assert components["n_valid"] + components["n_excess"] == components["n_network_sim"]
        assert components["n_valid"] + components["n_missing"] == components["n_network_obs"]

    def test_the_tail_shape_is_reported(self, bench, geometry) -> None:
        # D_so and D_os are tail statistics, not typical gaps: a median of zero
        # with a heavy top decile is the normal shape, and r_optim compares a
        # two-pixel threshold against it.
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        for key in ("D_so_median", "D_so_p90", "D_so_top5_share", "D_os_top5_share"):
            assert np.isfinite(result.components[key])
        assert 0.0 <= result.components["D_so_top5_share"] <= 1.0

    def test_an_observed_network_outside_the_catchment_is_refused(self, bench, geometry) -> None:
        with pytest.raises(ValueError, match="holds no cell inside the catchment"):
            _evaluate(bench, geometry, np.zeros(N_CELLS, dtype=bool), 200.0)

    def test_the_distance_method_has_one_name(self) -> None:
        assert DISTANCE_METHOD == "downslope_simclosed_obsraw_outletsealed"


class TestWaterBodyWiring:
    """The bridge between the built model and the two supports.

    The mask is only as good as the attribute it reads: a name no backend ever
    writes gives an empty exclusion and a silently wrong criterion on every
    catchment holding a reservoir.
    """

    def _lake_cells(self) -> list[int]:
        return [cell_id(row, AXIS_COL) for row in range(40, 45)]

    def test_the_lake_cells_a_model_carries_leave_both_supports(self, bench, geometry) -> None:
        cells = self._lake_cells()
        model = SimpleNamespace(open_water_cell_ids=list(cells))
        mask = water_body_mask(model, n_cells=N_CELLS)

        assert mask is not None
        assert sorted(np.flatnonzero(mask).tolist()) == sorted(cells)

        observed = observed_network("aligned")
        without = _evaluate(bench, geometry, observed, 200.0)
        with_lake = _evaluate(bench, geometry, observed, 200.0, excluded=mask)
        assert with_lake.components["n_network_obs"] < without.components["n_network_obs"]
        assert with_lake.components["n_network_sim"] < without.components["n_network_sim"]

    def test_a_model_without_lakes_leaves_the_supports_untouched(self, bench, geometry) -> None:
        assert water_body_mask(SimpleNamespace(open_water_cell_ids=[]), n_cells=N_CELLS) is None
        assert water_body_mask(SimpleNamespace(), n_cells=N_CELLS) is None

        observed = observed_network("aligned")
        without = _evaluate(bench, geometry, observed, 200.0)
        with_none = _evaluate(bench, geometry, observed, 200.0, excluded=None)
        assert with_none.signed_gap == pytest.approx(without.signed_gap)

    def test_a_cell_outside_the_mesh_is_dropped(self) -> None:
        model = SimpleNamespace(open_water_cell_ids=[3, N_CELLS, -1])
        mask = water_body_mask(model, n_cells=N_CELLS)
        assert np.flatnonzero(mask).tolist() == [3]

    def test_the_modflow6_builder_writes_the_attribute_the_criterion_reads(self) -> None:
        # The defect this guards is invisible at runtime: the criterion reads an
        # attribute, gets None, and reports a plausible number.
        source = (Path(hydromodpy.__file__).parent / "solver" / "modflow6" / "build.py").read_text(
            encoding="utf-8"
        )
        assert "model.open_water_cell_ids = " in source


class TestRechargeProvenance:
    """The denominator of the calibrated ratio has to leave a trace.

    The criterion calibrates ``K/R``, so the one per cent bound holds on the
    conductivity alone while ``R`` stays put. A recharge that moves between two
    trials changes the calibrated quantity without changing any declared
    parameter, which is invisible unless every trial records the value it ran
    with.
    """

    def _geometry(self, bench, recharge: float, ratio: float = 1e-2):
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        return build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=recharge,
            tau_specific_ratio=ratio,
            diagonal_neighbors=True,
        )

    def test_the_geometry_publishes_the_recharge_it_used(self, bench) -> None:
        geometry = self._geometry(bench, 3.2e-8)
        assert geometry.diagnostics["R_mean_m_s"] == pytest.approx(3.2e-8)

    def test_the_published_recharge_is_the_one_the_threshold_was_built_from(self, bench) -> None:
        # Read the recharge back out of the seepage threshold rather than out
        # of the call: the diagnostic is only provenance if it is the number
        # that actually divided the ratio.
        geometry = self._geometry(bench, 3.2e-8, ratio=1e-2)
        area = CELL_SIZE * CELL_SIZE
        applied = float(geometry.threshold_m3_s[0]) / (area * 1e-2)
        assert applied == pytest.approx(geometry.diagnostics["R_mean_m_s"], rel=1e-12)

    def test_a_recharge_that_moves_is_warned_about_and_names_both_values(
        self, bench, caplog
    ) -> None:
        with recharge_session("one-search"):
            self._geometry(bench, 3.2e-8)
            caplog.clear()
            with caplog.at_level("WARNING"):
                self._geometry(bench, 6.4e-8)
        assert "3.2e-08" in caplog.text
        assert "6.4e-08" in caplog.text

    def test_a_frozen_recharge_stays_silent(self, bench, caplog) -> None:
        with recharge_session("one-search"):
            self._geometry(bench, 3.2e-8)
            caplog.clear()
            with caplog.at_level("WARNING"):
                self._geometry(bench, 3.2e-8)
        assert "recharge" not in caplog.text


class TestSaturationCapSupport:
    """``L_cap`` has to be a length of the CATCHMENT, not of the model domain.

    The flood is seeded on the border of the domain and the catchment is what
    descends to the outlet on that graph, so a buffer beyond the divide never
    reaches the outlet: the cap is a length of the basin by construction.
    ``L_cap`` is the value most of ``D_os`` takes at the high end of a bracket,
    so a buffer that could reach the outlet across the divide would set it.
    """

    FIRST_ROW = 20

    def _geometry(self, bench, **kwargs):
        del bench
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        return build_network_geometry(
            topography=_divided_valley(self.FIRST_ROW),
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=3.2e-8,
            tau_specific_ratio=1e-2,
            delineated_catchment=_rows_from(self.FIRST_ROW),
            **kwargs,
        )

    def test_the_cap_majors_every_descent_of_the_catchment(self, bench) -> None:
        geometry = self._geometry(bench)
        outlet_mask = np.zeros(N_CELLS, dtype=bool)
        outlet_mask[geometry.outlet] = True
        to_outlet = downslope_distance_to_mask(geometry.metric, outlet_mask)

        inside = geometry.catchment & np.isfinite(to_outlet)
        assert inside.any()
        assert geometry.saturation_cap_m == pytest.approx(float(to_outlet[inside].max()))
        assert np.all(to_outlet[inside] <= geometry.saturation_cap_m + 1e-9)

    def test_nothing_beyond_the_divide_reaches_the_outlet(self, bench) -> None:
        geometry = self._geometry(bench)
        outlet_mask = np.zeros(N_CELLS, dtype=bool)
        outlet_mask[geometry.outlet] = True
        to_outlet = downslope_distance_to_mask(geometry.metric, outlet_mask)

        assert np.array_equal(geometry.catchment, _rows_from(self.FIRST_ROW))
        assert not np.any(np.isfinite(to_outlet[~geometry.catchment]))
        assert longest_descent_length(geometry.metric, outlet_mask) == pytest.approx(
            geometry.saturation_cap_m
        )

    def test_an_empty_support_is_refused_by_name(self, bench) -> None:
        geometry = self._geometry(bench)
        outlet_mask = np.zeros(N_CELLS, dtype=bool)
        outlet_mask[geometry.outlet] = True
        with pytest.raises(ValueError, match="inside the requested support"):
            longest_descent_length(
                geometry.metric, outlet_mask, within=np.zeros(N_CELLS, dtype=bool)
            )


class TestWaterBodiesInTheTarget:
    """Open water is surface water, so it belongs to the target of ``D_so``.

    A seepage cell fifty meters from a bank stops at the reservoir. Leaving the
    water body out of the target makes its descent cross the reservoir and carry
    on to the next mapped reach, which is kilometers on a real one, and inflates
    ``D_so`` with the size of the lake rather than with the hydrogeology.
    """

    def _lake(self) -> np.ndarray:
        # Off the mapped axis, on the hillside, so the union really adds cells.
        lake = np.zeros(N_CELLS, dtype=bool)
        lake[[cell_id(row, 8) for row in range(28, 34)]] = True
        return lake

    def _geometry(self, bench, excluded):
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        return build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=3.2e-8,
            tau_specific_ratio=1e-2,
            excluded=excluded,
            diagonal_neighbors=True,
        )

    def test_a_water_body_cell_is_at_distance_zero_from_the_target(self, bench) -> None:
        lake = self._lake()
        with_lake = self._geometry(bench, lake)
        without = self._geometry(bench, None)

        assert np.all(with_lake.distance_to_observed[lake] == 0.0)
        assert np.all(with_lake.distance_to_observed_raw[lake] == 0.0)
        # The same cells were a plain hillside before, so they had to descend.
        assert np.any(without.distance_to_observed[lake] > 0.0)

    def test_adding_the_water_body_can_only_shorten_a_descent(self, bench) -> None:
        lake = self._lake()
        with_lake = self._geometry(bench, lake)
        without = self._geometry(bench, None)

        finite = np.isfinite(without.distance_to_observed) & np.isfinite(
            with_lake.distance_to_observed
        )
        assert np.all(
            with_lake.distance_to_observed[finite] <= without.distance_to_observed[finite] + 1e-9
        )
        shortened = with_lake.distance_to_observed[finite] < without.distance_to_observed[finite]
        assert shortened.sum() > lake.sum(), "no cell upslope of the reservoir stops at it"

    def test_the_water_body_still_leaves_the_supports(self, bench) -> None:
        lake = self._lake()
        geometry = self._geometry(bench, lake)
        assert geometry.excluded is not None
        assert np.array_equal(geometry.excluded & lake, lake)

    def test_the_reachability_diagnostic_stays_on_the_mapped_network(self, bench) -> None:
        # Otherwise a reservoir absorbing paths would flatter the number that
        # says how well the linework agrees with the routing surface.
        lake = self._lake()
        with_lake = self._geometry(bench, lake)
        without = self._geometry(bench, None)
        assert with_lake.diagnostics["frac_reachable_obs_raw"] == pytest.approx(
            without.diagnostics["frac_reachable_obs_raw"]
        )
        assert with_lake.diagnostics["alpha_obs_closure"] == pytest.approx(
            without.diagnostics["alpha_obs_closure"]
        )


class TestSupportPartition:
    """One derivation of the three classes, for the counts and for a map.

    A confusion map draws what a trial counted. Deriving the partition twice is
    how a figure comes to disagree with the number it illustrates, so the cost
    reads it from the same place a caller would.
    """

    def _supports(self, bench, geometry, observed, threshold, excluded=None):
        return criterion_supports(
            simulated=_network_from_threshold(bench, threshold),
            observed=observed,
            catchment=geometry["catchment"],
            active=bench.metric.graph.active,
            excluded=excluded,
        )

    def test_the_three_classes_partition_the_two_supports(self, bench, geometry) -> None:
        supports = self._supports(bench, geometry, observed_network("aligned"), 200.0)
        assert np.array_equal(supports.valid | supports.excess, supports.support_so)
        assert np.array_equal(supports.valid | supports.missing, supports.support_os)
        assert not np.any(supports.excess & supports.missing)
        assert not np.any(supports.excess & supports.valid)

    def test_what_the_trial_counts_is_what_a_map_would_draw(self, bench, geometry) -> None:
        observed = observed_network("aligned")
        result = _evaluate(bench, geometry, observed, 200.0)
        supports = self._supports(bench, geometry, observed, 200.0)

        assert supports.counts == {
            "n_valid": result.components["n_valid"],
            "n_excess": result.components["n_excess"],
            "n_missing": result.components["n_missing"],
        }
        assert float(int(supports.seepage.sum())) == result.components["n_seepage"]
        assert float(int(supports.support_so.sum())) == result.components["n_network_sim"]
        assert float(int(supports.support_os.sum())) == result.components["n_network_obs"]

    def test_a_water_body_leaves_every_class(self, bench, geometry) -> None:
        observed = observed_network("aligned")
        lake = np.zeros(N_CELLS, dtype=bool)
        lake[[cell_id(row, AXIS_COL) for row in range(40, 45)]] = True
        supports = self._supports(bench, geometry, observed, 200.0, excluded=lake)

        for mask in (
            supports.keep,
            supports.support_so,
            supports.support_os,
            supports.valid,
            supports.excess,
            supports.missing,
            supports.seepage,
        ):
            assert not np.any(mask & lake)


class TestAlphaIsMeasuredOnTheScoredSupport:
    """``alpha_obs_closure`` on the whole mesh answers a different question.

    A mapped linework is routinely wider than the catchment it is used on: the
    hydrography of a department gets loaded, the catchment is one basin of it.
    Outside the catchment the mesh is a buffer, so nothing there is required to
    descend into the network, and the trace of those reaches inflates the
    closure without adding to the numerator. Measured on the Nancon when one
    outlet sealed the whole mesh, the raw linework put 1362 of its 2479 mapped
    cells outside the catchment and read 0.306 on the mesh against 0.693 on the
    catchment: a factor of two that says nothing about the agreement tested.

    The clipped bench holds a divide above row ``FIRST_ROW``: the rows north
    of it drain off the domain, so the catchment of the southern outlet is the
    rows below it, on the graph as on the polygon.
    """

    FIRST_ROW = 20

    def _geometry(self, bench, catchment, case="aligned", observed=None):
        clipped = not bool(np.all(catchment))
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        return build_network_geometry(
            topography=_divided_valley(self.FIRST_ROW) if clipped else bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network(case) if observed is None else observed,
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=3.2e-8,
            tau_specific_ratio=1e-2,
            delineated_catchment=catchment,
        )

    def _clipped_catchment(self):
        return _rows_from(self.FIRST_ROW)

    @pytest.mark.parametrize("case", ["aligned", "shifted", "hole", "truncated"])
    def test_both_ratios_are_the_ones_the_masks_hold(self, bench, case) -> None:
        geometry = self._geometry(bench, self._clipped_catchment(), case=case)
        closure = downstream_closure(geometry.metric, geometry.observed)
        inside = closure & geometry.catchment

        assert geometry.alpha_obs_closure == pytest.approx(geometry.observed.sum() / closure.sum())
        assert geometry.alpha_obs_closure_catchment == pytest.approx(
            (geometry.observed & geometry.catchment).sum() / inside.sum()
        )

    def test_a_catchment_holding_the_whole_network_makes_the_two_agree(self, bench) -> None:
        geometry = self._geometry(bench, np.ones(N_CELLS, dtype=bool))

        assert geometry.frac_obs_outside_catchment == pytest.approx(0.0)
        assert geometry.alpha_obs_closure_catchment == pytest.approx(geometry.alpha_obs_closure)

    def test_the_share_left_outside_is_the_one_the_masks_hold(self, bench) -> None:
        geometry = self._geometry(bench, self._clipped_catchment())

        # Rows 12 to 19 of the axis column are mapped and out of the catchment.
        outside = self.FIRST_ROW - FIRST_OBSERVED_ROW
        mapped = N_ROWS - FIRST_OBSERVED_ROW
        assert geometry.frac_obs_outside_catchment == pytest.approx(outside / mapped)

    def test_a_clipping_that_does_not_move_the_ratio_stays_silent(self, bench, caplog) -> None:
        # The axis is mapped on both sides of the divide, down to the northern
        # border and down to the outlet, so each reach closes on itself.
        observed = np.zeros(N_CELLS, dtype=bool)
        observed[[cell_id(row, AXIS_COL) for row in range(N_ROWS)]] = True
        with caplog.at_level("WARNING"):
            geometry = self._geometry(bench, self._clipped_catchment(), observed=observed)

        # A third of the mapped cells are out, over ground that routes on its
        # own, so both ratios read 1.000 and there is nothing to report.
        assert geometry.frac_obs_outside_catchment > 0.10
        assert geometry.alpha_obs_closure == pytest.approx(1.0)
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "outside the scored catchment" not in messages

    def test_a_reach_beyond_the_divide_that_moves_the_ratio_is_reported(
        self, bench, caplog
    ) -> None:
        # Rows 12 to 19 of the axis are mapped beyond the divide and drain north
        # through twelve unmapped cells: that trace alone moves the mesh ratio.
        with caplog.at_level("WARNING"):
            geometry = self._geometry(bench, self._clipped_catchment())

        assert geometry.alpha_obs_closure_catchment == pytest.approx(1.0)
        assert geometry.alpha_obs_closure < 0.9
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "outside the scored catchment" in messages

    def test_the_top_versus_map_warning_never_prescribes_a_burn(
        self, bench, caplog, monkeypatch
    ) -> None:
        # The warning prints once per process; this test reads it as the first.

        monkeypatch.setattr(stream_geometry, "_alpha_warned", False)
        with caplog.at_level("WARNING"):
            geometry = self._geometry(bench, np.ones(N_CELLS, dtype=bool), case="shifted")

        assert geometry.alpha_obs_closure_catchment < 0.90
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "alpha_obs_closure_catchment" in messages
        # The criterion descends the raw model top by design, so telling a user
        # to burn the routing DEM is advice they may already have followed, and
        # that would not move this number if they did.
        assert "urn the network" not in messages


# From test_the_overlap_indices_of_the_published_code.py
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


def test_the_indices_follow_the_published_definitions() -> None:
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


def test_a_length_is_the_sum_of_the_cell_sizes_on_the_scored_support() -> None:
    out = secondary_diagnostics(d_so=1.0, d_os=1.0, supports=_supports(), cell_area_m2=AREAS)

    # The simulated cell outside the catchment is not counted.
    assert out["L_sim_m"] == pytest.approx(40.0)
    assert out["L_obs_m"] == pytest.approx(30.0)


def test_the_ratio_is_not_a_number_when_d_os_is_zero_or_d_so_is_missing() -> None:
    supports = _supports()

    zero = secondary_diagnostics(d_so=5.0, d_os=0.0, supports=supports, cell_area_m2=AREAS)
    empty = secondary_diagnostics(d_so=math.nan, d_os=5.0, supports=supports, cell_area_m2=AREAS)

    assert math.isnan(zero["D_so_over_D_os"])
    assert math.isnan(empty["D_so_over_D_os"])
