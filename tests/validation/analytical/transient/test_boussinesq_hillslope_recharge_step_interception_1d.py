"""Validate the transient Boussinesq hillslope recharge-step interception case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.comparison import (
    run_boussinesq_hillslope_recharge_step_interception_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_boussinesq_hillslope_recharge_step_interception_1d_matches_onset_approximation() -> None:
    """Run the local Boussinesq case and compare the interception onset diagnostics."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=False,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_boussinesq_hillslope_recharge_step_interception_comparison(
        caller_file=__file__,
        solver="boussinesq",
    )
    onset_tol = dict(comparison.tolerances.get("onset", {}))
    trajectory_tol = dict(comparison.tolerances.get("trajectory", {}))
    uniformity_tol = dict(comparison.tolerances.get("uniformity", {}))
    contact_tol = dict(comparison.tolerances.get("contact", {}))

    assert_metric_below(
        "Onset-time error",
        comparison.onset_time_error_days,
        float(onset_tol["time_error_days"]),
        unit="day",
    )
    assert_metric_below(
        "Interception-trajectory RMSE",
        comparison.trajectory_rmse_m,
        float(trajectory_tol["rmse_m"]),
        unit="m",
    )
    assert_metric_below(
        "Interception-trajectory max abs error",
        comparison.trajectory_max_error_m,
        float(trajectory_tol["max_abs_error_m"]),
        unit="m",
    )
    assert_metric_below(
        "Trajectory reversal",
        comparison.trajectory_reversal_m,
        float(trajectory_tol["reversal_m"]),
        unit="m",
    )
    assert_metric_below(
        "Maximum positive clearance above topography",
        comparison.max_positive_clearance_m,
        float(contact_tol["max_positive_clearance_m"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(uniformity_tol["row_spread"]),
        unit="m",
    )
