"""Validate the steady Boussinesq circular-island piecewise-K case."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.boussinesq_circular_island_piecewise_k_2d.comparison import (
    run_boussinesq_circular_island_piecewise_k_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
def test_boussinesq_circular_island_piecewise_k_2d_matches_reference_profile() -> None:
    """Run the launcher case and compare the final annular profile to Boussinesq."""
    assert_required_executables(require_modpath=False, require_mt3dms=False)

    comparison = run_boussinesq_circular_island_piecewise_k_comparison(caller_file=__file__)
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
