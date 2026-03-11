"""Validate the linearized unconfined boundary-step case against its analytical reference."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.comparison import (
    run_linearized_unconfined_boundary_step_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_linearized_unconfined_boundary_step_1d_matches_reference_profiles() -> None:
    """Run the launcher case and compare the full transient profile matrix."""
    assert_required_executables(require_modpath=False, require_mt3dms=False)

    comparison = run_linearized_unconfined_boundary_step_comparison(caller_file=__file__)
    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    final_profile_tol = dict(comparison.tolerances.get("final_profile", {}))

    assert_metric_below(
        "Space-time RMSE",
        comparison.space_time_rmse,
        float(space_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Space-time max abs error",
        comparison.space_time_max_error,
        float(space_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Final-profile RMSE",
        comparison.final_profile_rmse,
        float(final_profile_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(space_time_tol["row_spread"]),
        unit="m",
    )
