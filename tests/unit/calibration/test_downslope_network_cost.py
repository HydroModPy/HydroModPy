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
    seepage_distance_cost,
)
from hydromodpy.calibration.observations.observed_network import water_body_mask
from hydromodpy.calibration.observations.simulated_network import (
    build_simulated_network,
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.core.topographic_distance import (
    downslope_distance_to_mask,
    longest_descent_length,
)
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    LENGTH_SCALE,
    N_CELLS,
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
        assert result.cost == pytest.approx(abs(result.signed_gap))
        assert result.components["J"] == pytest.approx(result.cost)
        assert result.components["J_signed"] == pytest.approx(result.signed_gap)

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
