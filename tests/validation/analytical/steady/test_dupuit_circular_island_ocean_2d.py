"""Validate a steady circular-island 2D case using the ocean boundary condition."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.comparison import (
    run_dupuit_circular_island_ocean_comparison,
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
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)

def test_dupuit_circular_island_ocean_2d_matches_reference_profile(solver: str, require_modflow: bool, require_modflow6: bool) -> None:
    """Run the launcher case and compare the final annular profile to Dupuit."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_dupuit_circular_island_ocean_comparison(caller_file=__file__, solver=solver)
    profile_tol = dict(comparison.tolerances.get("radial_profile", {}))

    assert_metric_below("Radial head-profile RMSE", comparison.rms_error, float(profile_tol["rmse"]), unit="m")
    assert_metric_below(
        "Radial head-profile max abs error",
        comparison.max_error,
        float(profile_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Azimuthal spread",
        comparison.azimuthal_spread,
        float(profile_tol["azimuthal_spread"]),
        unit="m",
    )
    assert_metric_below(
        "Ocean head max abs error",
        comparison.ocean_head_max_error,
        float(profile_tol["ocean_head_max_error"]),
        unit="m",
    )
    assert comparison.land_clearance_min >= float(profile_tol["min_land_clearance"]), (
        "Minimum land freeboard is below the configured tolerance: "
        f"{comparison.land_clearance_min:.4f} m < {float(profile_tol['min_land_clearance']):.4f} m"
    )



