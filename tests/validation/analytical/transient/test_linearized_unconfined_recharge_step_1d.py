"""Validate the linearized unconfined recharge-step case against its analytical reference."""

from __future__ import annotations

import platform

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.comparison import (
    run_linearized_unconfined_recharge_step_comparison,
)


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflownwt", True, False, id="modflownwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)
def test_linearized_unconfined_recharge_step_1d_matches_reference_profiles(
    solver: str, require_modflow: bool, require_modflow6: bool
) -> None:
    """Run the launcher case and compare the full transient profile matrix."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_linearized_unconfined_recharge_step_comparison(
        caller_file=__file__, solver=solver
    )
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


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.petsc
def test_linearized_unconfined_recharge_step_1d_petsc_ts_vi_obstacle_matches_reference_profiles() -> None:
    """Run the analytical recharge-step case through PETSc TS VI obstacle."""
    _require_linux_petsc4py()

    comparison = run_linearized_unconfined_recharge_step_comparison(
        caller_file=__file__,
        solver="petsc_ts_vi_obstacle",
    )
    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    final_profile_tol = dict(comparison.tolerances.get("final_profile", {}))

    assert comparison.result.solver_name == "petsc_ts_vi_obstacle"
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
