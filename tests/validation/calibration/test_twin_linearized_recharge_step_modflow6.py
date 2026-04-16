"""Validation benchmark for transient K+Sy twin calibration on MODFLOW 6."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
def test_calibration_twin_linearized_recharge_step_modflow6_benchmark_recovers_truth() -> None:
    """Run one budgeted transient twin benchmark and verify representative methods recover K+Sy."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    selected_profiles = tuple(
        profile
        for profile in TRANSIENT_RECHARGE_STEP_TWIN_CASE.method_profiles
        if profile.name in {"random_search", "gp_mapping"}
    )
    benchmark_definition = replace(
        TRANSIENT_RECHARGE_STEP_TWIN_CASE,
        method_profiles=selected_profiles,
        parameter_abs_tolerances={
            "K_global": 2.0e-5,
            "Sy_global": 0.03,
        },
    )

    benchmark = run_lightweight_twin_benchmark_case(
        benchmark_definition,
        caller_file=__file__,
        evaluation_budget=16,
    )

    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 2
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert_lightweight_method_result(result)
        if result.method_name in {"random_search", "simplex"}:
            assert result.recovered_truth, result.to_mapping()

    distribution_results = list(benchmark.method_results)
    assert len(distribution_results) == 2
    assert all(
        result.model_distribution_path is not None for result in distribution_results
    )
    assert next(
        result for result in distribution_results if result.method_name == "random_search"
    ).truth_in_distribution is True
    assert all(
        (
            result.truth_in_distribution is True
            or result.recovered_truth is True
        )
        for result in distribution_results
        if result.method_name in {"gp_mapping", "da_mh_gp"}
    )
