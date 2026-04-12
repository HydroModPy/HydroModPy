"""Validation benchmark for noisy transient K+Sy twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
def test_calibration_twin_linearized_recharge_step_noisy_modflow6_benchmark_recovers_truth() -> None:
    """Run the noisy transient twin benchmark and verify repeated methods remain stable."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_used["head_mid"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == 4

    random_results = [
        result
        for result in benchmark.method_results
        if result.method_name == "random_search"
    ]
    assert len(random_results) == 3
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.recovered_truth, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
    assert all(result.truth_in_distribution is True for result in random_results)
    assert sorted(result.seed for result in random_results) == [11, 23, 37]
