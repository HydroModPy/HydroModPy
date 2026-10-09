"""Validation of K and Sy recovery by calibration methods on a transient twin, MODFLOW 6.

Compared with: the hydraulic conductivity and specific yield that produced the observations.

A MODFLOW 6 run with K = 1e-4 m/s and Sy = 0.10 under a recharge step gives the head at
mid-aquifer and the outlet discharge. Each method then searches K in [5e-5, 3e-4] and Sy in
[0.04, 0.18] from those two series alone. This is the one well-posed two-parameter transient
calibration of the suite: the head series constrains Sy and the discharge series constrains K.
CMA-ES, Nelder-Mead and Optuna are asserted to land within the case tolerance of the truth
(1.5e-5 on K, 0.04 on Sy). Random search, GP mapping and DA-MH-GP also run; their distances to
the truth are recorded for information and not asserted, because their budget does not
guarantee a hit on a smooth two-parameter surface.
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
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.slow
def test_calibration_twin_linearized_recharge_step_modflow6_benchmark_recovers_truth() -> None:
    """Run the data-rich transient K+Sy twin and verify the smooth-surface methods recover it."""
    pytest.importorskip("optuna")
    pytest.importorskip("cma")
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_lightweight_twin_benchmark_case(
        TRANSIENT_RECHARGE_STEP_TWIN_CASE,
        caller_file=__file__,
        checks={
            "optuna": TwinCheck(best_within=1.0),
            "cma_es": TwinCheck(best_within=1.0),
            "scipy_nelder_mead": TwinCheck(best_within=1.0),
        },
    )

    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 6
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_global" in result.param_abs_error
        assert "Sy_global" in result.param_abs_error
        assert_lightweight_method_result(result)
    for result in benchmark.method_results:
        if result.method_name in {"random_search", "gp_mapping", "da_mh_gp"}:
            assert result.model_distribution_path is not None
            assert result.model_distribution_path.is_file()
