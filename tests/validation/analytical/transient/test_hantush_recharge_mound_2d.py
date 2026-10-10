"""Validate the growth of a groundwater mound under a rectangle of recharge against Hantush (1967).

Compared with: the Hantush (1967) mound linearized with the mean saturated thickness, `h^2 - hi^2 = (w / 2K) nu t sum S*(...)` over the four corners, `nu = K b / Sy`, `b = (hi + hm(t)) / 2`, read at the centre of each solver cell: at the centre over time, on a transect through it, and over the plan at the final time.
"""

from __future__ import annotations

import platform

import numpy as np
import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison, record_series
from validation_cases.analytical.transient.hantush_recharge_mound_2d.comparison import (
    run_hantush_recharge_mound_comparison,
)


def _assert_mound_case(*, solver: str) -> None:
    """Run one solver and compare its mound with the Hantush solution."""
    comparison = run_hantush_recharge_mound_comparison(caller_file=__file__, solver=solver)
    assert comparison.result.solver_name == solver
    record_comparison(comparison)
    record_series(
        "Head rise at the centre",
        comparison.elapsed_days,
        comparison.analytical_centre_rise,
        comparison.numerical_centre_rise,
        x_label="time (d)",
        y_label="head rise (m)",
    )

    assert np.all(np.isfinite(comparison.numerical_profiles))
    space_time_tol = dict(comparison.tolerances["space_time"])
    final_tol = dict(comparison.tolerances["final_time"])
    assert_metric_below(
        "Transect space-time RMSE",
        comparison.space_time_rmse,
        float(space_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Transect space-time max abs error",
        comparison.space_time_max_error,
        float(space_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Centre rise max abs error",
        comparison.centre_max_error,
        float(space_time_tol["centre_max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Final transect RMSE", comparison.final_profile_rmse, float(final_tol["rmse"]), unit="m"
    )
    assert_metric_below(
        "Final map max abs error",
        comparison.map_max_error,
        float(final_tol["map_max_abs_error"]),
        unit="m",
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("modflow6_voronoi", False, True, id="modflow6_voronoi"),
    ],
)
def test_recharge_mound_matches_hantush_modflow(
    solver: str, require_modflow: bool, require_modflow6: bool
) -> None:
    """Grow the mound with MODFLOW on the grid, the conforming triangles and the Voronoi dual."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )
    _assert_mound_case(solver=solver)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize("solver", [pytest.param("boussinesq_local", id="boussinesq_local")])
def test_recharge_mound_matches_hantush_default_engine(solver: str) -> None:
    """Grow the mound with the default Boussinesq engine, which needs no PETSc.

    The mesh has 6806 triangles, so 'auto' runs the sparse engine.
    """
    _assert_mound_case(solver=solver)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.petsc
@pytest.mark.parametrize("solver", [pytest.param("boussinesq", id="boussinesq")])
def test_recharge_mound_matches_hantush_boussinesq_petsc(solver: str) -> None:
    """Grow the mound with the Boussinesq PETSc runtime."""
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")
    _assert_mound_case(solver=solver)
