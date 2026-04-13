"""Validation benchmark for one mesh-perturbed steady scalar-K twin on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_mesh_perturbed_modflow6_recovers_truth_under_mesh_mismatch() -> None:
    """Run the mesh-perturbed steady twin benchmark and verify recovery remains usable."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is not None
    assert benchmark.configuration_figure.is_file()
    assert benchmark.pruned_artifacts
    assert benchmark.simulation_config_path.is_file()
    assert benchmark.truth_simulation_config_path.is_file()
    assert benchmark.simulation_config_path != benchmark.truth_simulation_config_path
    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 3
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert "K_global_factor" in result.param_abs_error
        assert result.objective_trace_figure is not None
        assert result.objective_trace_figure.is_file()
        assert result.objective_landscape_figure is not None
        assert result.objective_landscape_figure.is_file()

    deterministic = [
        result
        for result in benchmark.method_results
        if result.method_name in {"grid_search", "simplex"}
    ]
    assert all(result.recovered_truth for result in deterministic)

    random_result = next(
        result
        for result in benchmark.method_results
        if result.method_name == "random_search"
    )
    assert random_result.model_distribution_sample_count >= 1
    assert random_result.truth_in_distribution is True
