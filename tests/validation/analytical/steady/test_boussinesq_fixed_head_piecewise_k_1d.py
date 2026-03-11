"""Validate the steady Boussinesq fixed-head piecewise-K case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.boussinesq_fixed_head_piecewise_k_1d.comparison import (
    run_boussinesq_fixed_head_piecewise_k_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
def test_boussinesq_fixed_head_piecewise_k_1d_matches_reference_profile() -> None:
    """Run the launcher case and compare the final head profile to Boussinesq."""
    assert_required_executables(require_modpath=False, require_mt3dms=False)

    comparison = run_boussinesq_fixed_head_piecewise_k_comparison(caller_file=__file__)
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
