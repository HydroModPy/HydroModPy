"""Validation benchmark for noisy steady scalar-K twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_NOISY_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_noisy_modflow6_benchmark_recovers_truth() -> None:
    """Run the noisy steady twin benchmark and verify repeated methods stay usable."""
    pytest.importorskip("cma")

    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_NOISY_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.observations_truth["q_east"]
    assert benchmark.observations_used["q_east"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == 6

    random_results = [
        result
        for result in benchmark.method_results
        if result.method_name == "random_search"
    ]
    assert len(random_results) == 3
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
        if result.method_name in {"grid_search", "simplex", "cma_es"}:
            assert result.meets_success_target, result.to_mapping()
            assert result.recovered_truth, result.to_mapping()
    assert sum(1 for result in random_results if result.meets_success_target) >= 2
    assert sum(1 for result in random_results if result.recovered_truth) >= 2
    assert sum(1 for result in random_results if result.truth_in_distribution is True) >= 2
    assert sorted(result.seed for result in random_results) == [7, 11, 19]
