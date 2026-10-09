"""Validation benchmark for steady piecewise-K twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    TwinCheck,
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_boussinesq_fixed_head_piecewise_k_modflow6_benchmark_recovers_truth() -> (
    None
):
    """Run the steady piecewise-K twin benchmark and verify zoned K recovery."""
    pytest.importorskip("optuna")
    pytest.importorskip("cma")

    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_lightweight_twin_benchmark_case(
        PIECEWISE_K_TWIN_CASE,
        caller_file=__file__,
        checks={
            "random_search": TwinCheck(meets_target=True, in_distribution=True),
            "scipy_nelder_mead": TwinCheck(best_within=1.5),
            "cma_es": TwinCheck(best_within=5.0, second_smallest_within=2.0),
        },
    )

    assert benchmark.observations_truth["head_west"]
    assert benchmark.observations_truth["head_middle"]
    assert benchmark.observations_truth["head_east"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 5
    random_results = [
        result for result in benchmark.method_results if result.method_name == "random_search"
    ]
    optuna_result = next(
        result for result in benchmark.method_results if result.method_name == "optuna"
    )
    assert len(random_results) == 2
    assert optuna_result.model_distribution_sample_count >= 1
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_west" in result.param_abs_error
        assert "K_middle" in result.param_abs_error
        assert "K_east" in result.param_abs_error
        assert_lightweight_method_result(result)
    assert all(result.model_distribution_sample_count >= 96 for result in random_results)
