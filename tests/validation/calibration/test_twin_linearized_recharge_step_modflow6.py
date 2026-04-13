"""Validation benchmark for transient K+Sy twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
def test_calibration_twin_linearized_recharge_step_modflow6_benchmark_recovers_truth() -> None:
    """Run the transient twin benchmark and verify standardized methods recover K+Sy."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        TRANSIENT_RECHARGE_STEP_TWIN_CASE,
        caller_file=__file__,
        evaluation_budget=8,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is not None
    assert benchmark.configuration_figure.is_file()
    assert benchmark.pruned_artifacts
    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 3
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.objective_trace_figure is not None
        assert result.objective_trace_figure.is_file()
        assert result.objective_landscape_figure is not None
        assert result.objective_landscape_figure.is_file()
        if result.method_name in {"random_search", "simplex"}:
            assert result.recovered_truth, result.to_mapping()

    distribution_results = [
        result
        for result in benchmark.method_results
        if result.method_name in {"random_search", "gp_mapping"}
    ]
    assert len(distribution_results) == 2
    assert all(
        result.model_distribution_path is not None for result in distribution_results
    )
    assert all(
        result.truth_in_distribution is True for result in distribution_results
    )
