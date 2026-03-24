"""Validate the linearized unconfined boundary-piecewise case against its analytical reference."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.linearized_unconfined_boundary_piecewise_1d.comparison import (
    run_linearized_unconfined_boundary_piecewise_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflownwt", True, False, id="modflownwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)

def test_linearized_unconfined_boundary_piecewise_1d_matches_reference_profiles(solver: str, require_modflow: bool, require_modflow6: bool) -> None:
    """Run the launcher case and compare the full transient profile matrix."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_linearized_unconfined_boundary_piecewise_comparison(caller_file=__file__, solver=solver)
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



