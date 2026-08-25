"""The signed gap criterion, on the V-valley bench.

The bench is the same one the support study runs, so the cost function is
driven here exactly as a calibration drives it: a sweep over a threshold
standing in for ``K/R``, and the residual read at each point.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy
from hydromodpy.calibration.metrics.downslope_network import (
    DISTANCE_METHOD,
    SeepageDistanceResult,
    seepage_distance_cost,
)
from hydromodpy.calibration.observations.observed_network import water_body_mask
from hydromodpy.core.stream_geometry import build_network_geometry, criterion_supports
from hydromodpy.core.stream_network import (
    SimulatedNetwork,
    build_simulated_network,
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.core.topographic_distance import (
    downslope_distance_to_mask,
    longest_descent_length,
)
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
        # The optimizer reads the components; a second copy of J and Doptim on
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
        r_optim = [r.components["roptim"] for r in rejected if r.status == "ok"]
        assert r_optim, "the shifted case produced no evaluable point"
        assert max(r_optim) > 2.0

    def test_an_aligned_network_stays_inside_the_validity_bound(self, bench, geometry) -> None:
        result = _evaluate(bench, geometry, observed_network("aligned"), 200.0)
        assert result.components["roptim"] < 2.0
        assert result.components["roptim_valid"] == 1.0

    def test_the_unreachable_guard_fails_the_trial(self, bench, geometry) -> None:
        # Cut the catchment in half so most of the observed support can no
        # longer reach anything: the trial must fail loudly rather than average
        # over a truncated support.
        observed = observed_network("aligned")
        result = _evaluate(bench, geometry, observed, 200.0, max_unreachable_fraction=-1.0)
        assert result.status == "failed"


class TestTheUnreachableGuardIsOneSided:
    """The bound holds on ``D_so`` and on nothing else.

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
            max_unreachable_fraction=0.05,
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

    def test_a_simulated_support_that_cannot_descend_fails_the_trial(self, bench, geometry) -> None:
        # The same trial, with the descent to the mapped network taken away:
        # this is the side the bound is on.
        result = self._evaluate(
            bench, geometry, self._truncated_network(), np.full(N_CELLS, np.inf)
        )

        assert result.components["frac_unreachable_so"] == pytest.approx(1.0)
        assert result.status == "failed"


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
        # with a heavy top decile is the normal shape, and roptim compares a
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
        self._geometry(bench, 3.2e-8)
        caplog.clear()
        with caplog.at_level("WARNING"):
            self._geometry(bench, 6.4e-8)
        assert "3.2e-08" in caplog.text
        assert "6.4e-08" in caplog.text

    def test_a_frozen_recharge_stays_silent(self, bench, caplog) -> None:
        self._geometry(bench, 3.2e-8)
        caplog.clear()
        with caplog.at_level("WARNING"):
            self._geometry(bench, 3.2e-8)
        assert "recharge" not in caplog.text


class TestSaturationCapSupport:
    """``L_cap`` has to be a length of the CATCHMENT, not of the model domain.

    The flood is seeded on the single catchment outlet and walks the whole
    active surface, so after it every active cell holds a descent to that
    outlet. A maximum taken over the graph therefore follows the model domain,
    while ``L_cap`` is the value most of ``D_os`` takes at the high end of a
    bracket. The bench makes the two differ by construction: the top third of
    the valley is declared out of the catchment while staying in the mesh, and
    its cells reach the outlet by a path that crosses the whole catchment
    first, so they are strictly longer than anything inside it.
    """

    FIRST_ROW = 20

    def _geometry(self, bench, **kwargs):
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        catchment = np.zeros(N_CELLS, dtype=bool)
        for row in range(self.FIRST_ROW, N_ROWS):
            for col in range(N_COLS):
                catchment[cell_id(row, col)] = True
        return build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=3.2e-8,
            tau_specific_ratio=1e-2,
            delineated_catchment=catchment,
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

    def test_the_cap_ignores_what_lies_outside_the_catchment(self, bench) -> None:
        geometry = self._geometry(bench)
        outlet_mask = np.zeros(N_CELLS, dtype=bool)
        outlet_mask[geometry.outlet] = True
        to_outlet = downslope_distance_to_mask(geometry.metric, outlet_mask)

        outside = ~geometry.catchment & np.isfinite(to_outlet)
        # The rows above the catchment stay in the graph and reach the outlet by
        # crossing the catchment first, so their descent is strictly longer.
        assert outside.any()
        assert float(to_outlet[outside].max()) > geometry.saturation_cap_m
        assert longest_descent_length(geometry.metric, outlet_mask) > geometry.saturation_cap_m

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

    A seepage cell fifty metres from a bank stops at the reservoir. Leaving the
    water body out of the target makes its descent cross the reservoir and carry
    on to the next mapped reach, which is kilometres on a real one, and inflates
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
