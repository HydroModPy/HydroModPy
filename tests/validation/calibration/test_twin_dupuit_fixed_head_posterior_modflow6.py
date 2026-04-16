"""Validation benchmark for posterior-oriented steady scalar-K calibration on MODFLOW 6."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
def test_calibration_twin_dupuit_fixed_head_posterior_modflow6_distribution_methods_cover_truth() -> None:
    """Run the posterior-oriented steady twin benchmark and verify truth coverage."""
    pytest.importorskip("cma")

    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
        caller_file=__file__,
    )

    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 4
    for result in benchmark.method_results:
        assert result.meets_success_target, result.to_mapping()
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        if result.method_name in {"random_search", "gp_mapping", "da_mh_gp"}:
            assert result.model_distribution_sample_count >= 1, result.to_mapping()
            assert result.truth_in_distribution is True, result.to_mapping()
        else:
            assert result.recovered_truth, result.to_mapping()
        assert_lightweight_method_result(result)
