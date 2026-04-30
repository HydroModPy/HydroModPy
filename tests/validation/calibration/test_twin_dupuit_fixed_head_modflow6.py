"""Validate the steady same-solver twin benchmark for calibration."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)


def _assert_modflow6_runtime_available() -> None:
    """Require the MODFLOW 6 runtime used by the Dupuit twin benchmarks."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_modflow6_benchmark_recovers_truth() -> None:
    """Run the steady twin benchmark and verify standardized methods recover the truth."""
    pytest.importorskip("cma")

    _assert_modflow6_runtime_available()

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 5
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.recovered_truth, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_global" in result.param_abs_error
        assert_lightweight_method_result(result)
        if result.method_name == "random_search":
            assert result.model_distribution_sample_count >= 1
            assert result.truth_in_distribution is True


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.mf6
@pytest.mark.skip(
    reason=(
        "Path grammar mismatch in materialize_candidate: target "
        "'flow.param.K.value' matches the resolved Pydantic path used by "
        "apply_parameter_to_config but is invalid in the TOML overlay "
        "(FieldParamConfig forbids extra 'value' alongside "
        "field_homogeneous). Either teach materialize_candidate to "
        "translate Pydantic-resolved paths back to TOML grammar, or split "
        "TwinParameterTarget into (toml_target, runtime_target). Tracked "
        "post-v1.0."
    )
)
def test_calibration_twin_dupuit_fixed_head_modflow6_fast_grid_search_smoke() -> None:
    """Run one budget-capped smoke benchmark that stays genuinely quick."""
    _assert_modflow6_runtime_available()

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=__file__,
        method_names=("grid",),
        evaluation_budget=6,
    )

    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 1
    result = benchmark.method_results[0]
    assert result.method_name == "grid"
    assert result.requested_evaluation_budget == 6
    assert result.n_evaluations == 6
    assert result.meets_success_target, result.to_mapping()
    assert result.recovered_truth, result.to_mapping()
    assert result.cost_best is not None
    assert math.isfinite(float(result.cost_best)), result.to_mapping()
    assert result.session_prepare_time_seconds is not None
    assert result.mean_candidate_total_time_seconds is not None
    assert result.mean_candidate_preparation_time_seconds is not None
    assert result.mean_candidate_simulation_time_seconds is not None
    assert "K_global" in result.param_abs_error
    assert_lightweight_method_result(result)
