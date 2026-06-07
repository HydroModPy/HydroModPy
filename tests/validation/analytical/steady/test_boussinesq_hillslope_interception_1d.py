"""Validate the steady Boussinesq hillslope-interception benchmark."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.comparison import (
    run_boussinesq_hillslope_interception_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
def test_boussinesq_hillslope_interception_1d_matches_reference_position() -> None:
    """Run the PETSc VI Boussinesq case and compare emergence position."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=False,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_boussinesq_hillslope_interception_comparison(
        caller_file=__file__,
        solver="boussinesq",
    )
    interception_tol = dict(comparison.tolerances.get("interception", {}))
    uniformity_tol = dict(comparison.tolerances.get("uniformity", {}))
    contact_tol = dict(comparison.tolerances.get("contact", {}))

    assert_metric_below(
        "Interception x error",
        comparison.interception_x_error_m,
        float(interception_tol["x_error_m"]),
        unit="m",
    )
    assert_metric_below(
        "Maximum positive clearance above topography",
        comparison.max_clearance_m,
        float(contact_tol["max_positive_clearance_m"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(uniformity_tol["row_spread"]),
        unit="m",
    )
