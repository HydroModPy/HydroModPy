"""Validate the steady linearized unconfined drainage case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.analytical.steady.linearized_unconfined_drainage_1d.comparison import (
    run_linearized_unconfined_drainage_comparison,
)

NOT_APPLICABLE = {
    "boussinesq_local": (
        "The default local engine closes the land surface with a regularized partition "
        "that releases at the surface all the water a cell receives once its head reaches "
        "the drain elevation. It cannot hold a head above the drain, so the "
        "finite-conductance drain flux stays at zero."
    ),
}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("modflow6_voronoi", False, True, id="modflow6_voronoi"),
        pytest.param("boussinesq", False, False, id="boussinesq", marks=pytest.mark.petsc),
    ],
)
def test_linearized_unconfined_drainage_1d_matches_reference_profile(
    solver: str, require_modflow: bool, require_modflow6: bool
) -> None:
    """Run the case on each grid and compare the head profile to the linearized drainage reference.

    The grids are the structured MODFLOW grid, the triangle strip, its Voronoi dual and the
    PETSc Boussinesq strip, whose finite-conductance drain lets the head stand above the surface.
    """
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_linearized_unconfined_drainage_comparison(caller_file=__file__, solver=solver)
    record_comparison(comparison)
    profile_tol = dict(comparison.tolerances.get("head_profile", {}))

    assert_metric_below(
        "Head-profile RMSE", comparison.rms_error, float(profile_tol["rmse"]), unit="m"
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
