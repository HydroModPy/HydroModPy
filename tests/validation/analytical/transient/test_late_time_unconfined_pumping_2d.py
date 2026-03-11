"""Validate a transient unconfined pumping case against a late-time radial reference."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.late_time_unconfined_pumping_2d.comparison import (
    run_late_time_unconfined_pumping_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_late_time_unconfined_pumping_2d_matches_late_time_reference() -> None:
    """Run the launcher case and compare late-time radial drawdowns."""
    assert_required_executables(require_modpath=False, require_mt3dms=False)

    comparison = run_late_time_unconfined_pumping_comparison(caller_file=__file__)
    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    final_time_tol = dict(comparison.tolerances.get("final_time", {}))

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
        "Final-time RMSE",
        comparison.final_time_rmse,
        float(final_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Final-time max abs error",
        comparison.final_time_max_error,
        float(final_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Azimuthal spread",
        comparison.azimuthal_spread,
        float(space_time_tol["azimuthal_spread"]),
        unit="m",
    )
