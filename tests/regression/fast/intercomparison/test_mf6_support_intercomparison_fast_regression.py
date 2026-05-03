"""Fast MODFLOW 6 structured-vs-irregular support intercomparison."""

from __future__ import annotations

import pytest

from tests.regression.validation_profile_intercomparison_helpers import (
    run_validation_profile_intercomparison_regression,
)


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.intercomparison
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.timeout(900)
def test_modflow6_structured_and_irregular_tri_uniform_recharge_profiles_remain_close(
    update_goldens,
) -> None:
    """Lock MF6 structured and MF6 irregular-triangle profiles against each other."""
    run_validation_profile_intercomparison_regression(
        test_file=__file__,
        comparison_module=(
            "validation_cases.analytical.steady.dupuit_uniform_recharge_1d.comparison"
        ),
        comparison_function="run_dupuit_uniform_recharge_comparison",
        case_id="dupuit_uniform_recharge_1d",
        reference_solver="modflow6",
        candidate_solver="modflow6_irregular_tri",
        golden_filename=(
            "intercomparison/"
            "intercomparison_mf6_structured_irregular_dupuit_uniform_recharge.json"
        ),
        update_goldens=update_goldens,
        limits={
            "pair_rmse_max": 0.08,
            "pair_max_abs_error_max": 0.15,
            "reference_rmse_max": 0.08,
            "candidate_rmse_max": 0.05,
            "candidate_max_abs_error_max": 0.08,
        },
    )
