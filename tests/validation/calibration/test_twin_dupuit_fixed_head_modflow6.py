"""Validate the steady same-solver twin benchmark for calibration."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_modflow6_benchmark_recovers_truth() -> None:
    """Run the steady twin benchmark and verify standardized methods recover the truth."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.summary_path.is_file()
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 3
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.recovered_truth, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
        assert "K_global_factor" in result.param_abs_error
        if result.method_name == "random_search":
            assert result.model_distribution_sample_count >= 1
            assert result.truth_in_distribution is True
