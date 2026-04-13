"""Validation benchmark for noisy steady scalar-K twin calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_NOISY_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_noisy_modflow6_benchmark_recovers_truth() -> None:
    """Run the noisy steady twin benchmark and verify repeated methods stay usable."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        STEADY_DUPUIT_NOISY_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.observations_truth["q_east"]
    assert benchmark.observations_used["q_east"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == 5

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
    assert sorted(result.seed for result in random_results) == [7, 11, 19]
