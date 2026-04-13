"""Validation benchmark for steady piecewise-K twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_boussinesq_fixed_head_piecewise_k_modflow6_benchmark_recovers_truth() -> None:
    """Run the steady piecewise-K twin benchmark and verify zoned K recovery."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        PIECEWISE_K_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is not None
    assert benchmark.configuration_figure.is_file()
    assert benchmark.pruned_artifacts
    assert benchmark.observations_truth["head_west"]
    assert benchmark.observations_truth["head_middle"]
    assert benchmark.observations_truth["head_east"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 3
    random_results = [
        result
        for result in benchmark.method_results
        if result.method_name == "random_search"
    ]
    simplex_result = next(
        result
        for result in benchmark.method_results
        if result.method_name == "simplex"
    )
    assert len(random_results) == 2
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_west" in result.param_abs_error
        assert "K_middle" in result.param_abs_error
        assert "K_east" in result.param_abs_error
        assert result.objective_trace_figure is not None
        assert result.objective_trace_figure.is_file()
        assert result.objective_landscape_figure is not None
        assert result.objective_landscape_figure.is_file()
    assert simplex_result.recovered_truth, simplex_result.to_mapping()
    assert all(result.truth_in_distribution is True for result in random_results)
    assert all(
        result.model_distribution_sample_count >= 96 for result in random_results
    )
