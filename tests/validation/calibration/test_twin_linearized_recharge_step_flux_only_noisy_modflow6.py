"""Validation benchmark for a weakly identified transient flux-only K+Sy twin on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
def test_calibration_twin_linearized_recharge_step_flux_only_noisy_modflow6_benchmark_stays_informative() -> None:
    """Run the weakly identified flux-only transient twin and verify all methods remain informative."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
        caller_file=__file__,
        evaluation_budget=18,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is not None
    assert benchmark.configuration_figure.is_file()
    assert benchmark.pruned_artifacts
    assert benchmark.observations_truth["q_east"]
    assert benchmark.observations_used["q_east"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == 5

    distribution_results = [
        result
        for result in benchmark.method_results
        if result.method_name in {"random_search", "gp_mapping", "da_mh_gp"}
    ]
    point_results = [
        result
        for result in benchmark.method_results
        if result.method_name in {"cma_es", "simplex"}
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
        assert result.objective_trace_figure is not None
        assert result.objective_trace_figure.is_file()
        assert result.objective_landscape_figure is not None
        assert result.objective_landscape_figure.is_file()

    assert len(distribution_results) == 3
    assert any(result.meets_success_target for result in distribution_results)
    for result in distribution_results:
        assert result.model_distribution_path is not None
        assert result.model_distribution_path.is_file()
        assert result.model_distribution_sample_count > 0

    assert len(point_results) == 2
    for result in point_results:
        ratios = [
            float(value) / float(tolerance)
            for name, value in result.param_abs_error.items()
            if (tolerance := TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE.parameter_abs_tolerances.get(name)) is not None
        ]
        assert ratios
        assert all(math.isfinite(ratio) for ratio in ratios), result.to_mapping()
        assert max(ratios) <= 8.0, result.to_mapping()
