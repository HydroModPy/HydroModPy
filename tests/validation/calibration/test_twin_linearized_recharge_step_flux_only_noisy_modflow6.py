"""Wiring smoke test of six calibration methods on a flux-only K+Sy twin, MODFLOW 6.

Compared with: nothing. It is not a recovery validation. Each method gets 6 evaluations on
noisy outlet discharge alone, so a best point is close to a random draw. The test checks that
every method runs and returns finite costs, that at least one distribution method lands within
tolerance of the truth, and that the point methods stay within 8 times the tolerance. The
distances of the other methods to the truth are information only. The data-rich twin
(``test_twin_linearized_recharge_step_modflow6.py``) is the recovery check.
"""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    TwinCheck,
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
def test_calibration_twin_linearized_recharge_step_flux_only_noisy_modflow6_wiring_smoke() -> None:
    """Smoke test of the method wiring on a weakly identified flux-only twin, 6 evaluations each."""
    pytest.importorskip("optuna")
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_lightweight_twin_benchmark_case(
        TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
        caller_file=__file__,
        evaluation_budget=6,
        checks={
            "cma_es": TwinCheck(best_within=8.0),
            "scipy_nelder_mead": TwinCheck(best_within=8.0),
        },
        any_meets_target=("random_search", "optuna", "gp_mapping", "da_mh_gp"),
    )

    assert benchmark.observations_truth["q_east"]
    assert benchmark.observations_used["q_east"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == 6

    distribution_results = [
        result
        for result in benchmark.method_results
        if result.method_name in {"random_search", "optuna", "gp_mapping", "da_mh_gp"}
    ]

    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert_lightweight_method_result(result)

    assert len(distribution_results) == 4
    for result in distribution_results:
        assert result.model_distribution_path is not None
        assert result.model_distribution_path.is_file()
        assert result.model_distribution_sample_count > 0

    assert (
        sum(
            1
            for result in benchmark.method_results
            if result.method_name in {"cma_es", "scipy_nelder_mead"}
        )
        == 2
    )
