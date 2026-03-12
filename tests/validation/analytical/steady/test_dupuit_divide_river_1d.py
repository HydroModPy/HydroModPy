"""Validate a steady Dupuit 1D case with west-side divide and east-side river."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import (
    assert_metric_below,
)
from validation_cases.analytical.steady.dupuit_divide_river_1d.comparison import (
    run_dupuit_divide_river_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflownwt", True, False, id="modflownwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
    ],
)

def test_dupuit_divide_river_1d_matches_reference_profile(solver: str, require_modflow: bool, require_modflow6: bool) -> None:
    """Run the launcher case and compare the final head profile to Dupuit."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_dupuit_divide_river_comparison(caller_file=__file__, solver=solver)
    profile_tol = dict(comparison.tolerances.get("head_profile", {}))

    assert_metric_below("Head-profile RMSE", comparison.rms_error, float(profile_tol["rmse"]), unit="m")
    assert_metric_below(
        "Head-profile max abs error",
        comparison.max_error,
        float(profile_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(profile_tol["row_spread"]),
        unit="m",
    )



