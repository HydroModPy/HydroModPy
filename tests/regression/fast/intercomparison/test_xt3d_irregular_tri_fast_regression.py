"""Fast XT3D method-choice regression for MODFLOW 6 irregular triangles."""

from __future__ import annotations

import pytest

from tests.regression.xt3d_intercomparison_helpers import run_xt3d_method_choice_regression


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.intercomparison
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.timeout(900)
def test_modflow6_irregular_tri_xt3d_auto_improves_uniform_recharge(
    update_goldens,
) -> None:
    """Lock the XT3D auto-default on an irregular-triangle recharge case."""
    run_xt3d_method_choice_regression(
        test_file=__file__,
        case_slugs=("dupuit_uniform_recharge_1d",),
        golden_filename=(
            "intercomparison/intercomparison_xt3d_irregular_tri_dupuit_uniform_recharge.json"
        ),
        update_goldens=update_goldens,
        limits={
            "dupuit_uniform_recharge_1d": {
                "rmse_with_xt3d_max": 0.05,
                "max_error_with_xt3d_max": 0.08,
                "rmse_improvement_factor_min": 5.0,
            },
        },
    )
