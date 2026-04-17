"""Validate the steady sloping-substratum fixed-head case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.boussinesq_sloping_substratum_fixed_head_1d.comparison import (
    run_boussinesq_sloping_substratum_fixed_head_comparison,
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
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)
def test_boussinesq_sloping_substratum_fixed_head_1d_matches_reference_profile(
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Run the case and compare the final head profile to the exact reference."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_boussinesq_sloping_substratum_fixed_head_comparison(
        caller_file=__file__,
        solver=solver,
    )
    profile_tol = dict(comparison.tolerances.get("head_profile", {}))

    assert_metric_below(
        "Head-profile RMSE",
        comparison.rms_error,
        float(profile_tol["rmse"]),
        unit="m",
    )
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
