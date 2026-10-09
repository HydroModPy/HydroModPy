"""Validate the steady Boussinesq hillslope-interception benchmark."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.comparison import (
    run_boussinesq_hillslope_interception_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("boussinesq", marks=pytest.mark.petsc, id="boussinesq"),
        pytest.param("boussinesq_local", id="boussinesq_local"),
    ],
)
def test_boussinesq_hillslope_interception_1d_matches_reference_position(solver: str) -> None:
    """Run one Boussinesq variant and compare it to the exact seepage-face solution.

    ``boussinesq`` runs the PETSc VI obstacle; ``boussinesq_local`` runs the
    default engine with its regularized partition closure, without PETSc.
    """
    assert_required_executables(
        require_modflow=False,
        require_modflow6=False,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_boussinesq_hillslope_interception_comparison(
        caller_file=__file__,
        solver=solver,
    )
    record_comparison(comparison)
    interception_tol = dict(comparison.tolerances.get("interception", {}))
    profile_tol = dict(comparison.tolerances.get("profile", {}))
    uniformity_tol = dict(comparison.tolerances.get("uniformity", {}))
    contact_tol = dict(comparison.tolerances.get("contact", {}))

    assert_metric_below(
        "Head-profile RMSE", comparison.profile_rmse, float(profile_tol["rmse"]), unit="m"
    )
    assert_metric_below(
        "Head-profile max abs error",
        comparison.profile_max_error,
        float(profile_tol["max_abs_error"]),
        unit="m",
    )

    assert_metric_below(
        "Interception x error",
        comparison.interception_x_error_m,
        float(interception_tol["x_error_m"]),
        unit="m",
    )
    assert_metric_below(
        "Maximum positive clearance above topography",
        # The largest head above the ground, zero when the water table stays below it.
        max(comparison.max_clearance_m, 0.0),
        float(contact_tol["max_positive_clearance_m"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(uniformity_tol["row_spread"]),
        unit="m",
    )
