"""Validate the transient Boussinesq hillslope recharge-step interception case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.analytical.transient.boussinesq_hillslope_recharge_step_interception_1d.comparison import (
    run_boussinesq_hillslope_recharge_step_interception_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt", marks=pytest.mark.fast),
        pytest.param("modflow6", False, True, id="modflow6", marks=pytest.mark.fast),
        pytest.param(
            "modflow6_irregular_tri",
            False,
            True,
            id="modflow6_irregular_tri",
            marks=pytest.mark.fast,
        ),
        pytest.param(
            "modflow6_voronoi", False, True, id="modflow6_voronoi", marks=pytest.mark.fast
        ),
        pytest.param(
            "boussinesq",
            False,
            False,
            id="boussinesq",
            marks=[pytest.mark.petsc, pytest.mark.slow],
        ),
        pytest.param(
            "boussinesq_local", False, False, id="boussinesq_local", marks=pytest.mark.slow
        ),
    ],
)
def test_boussinesq_hillslope_recharge_step_interception_1d_matches_onset_approximation(
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Run one variant and compare the onset diagnostics.

    ``boussinesq`` runs the PETSc TS VI obstacle; ``boussinesq_local`` runs the
    default engine with its regularized partition closure, without PETSc. The
    MODFLOW variants drain the land surface through a DRN, which the 120 days
    never engage: the head stays below the surface, so the clearance bound
    there is the 1e-6 m of an obstacle.
    """
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_boussinesq_hillslope_recharge_step_interception_comparison(
        caller_file=__file__,
        solver=solver,
    )
    record_comparison(comparison)
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
        # The largest head above the ground, zero when the water table stays below it.
        max(comparison.max_positive_clearance_m, 0.0),
        float(contact_tol["max_positive_clearance_m"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(uniformity_tol["row_spread"]),
        unit="m",
    )
