"""Validate the thin-aquifer Brutsaert recession benchmark."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.transient.brutsaert_recession_boussinesq_thin_1d.comparison import (
    run_brutsaert_recession_boussinesq_thin_comparison,
)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflownwt", True, False, id="modflownwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)
def test_brutsaert_recession_boussinesq_thin_1d_matches_reference_recession(
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Run one solver variant and compare it to the nonlinear Brutsaert law."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_brutsaert_recession_boussinesq_thin_comparison(
        caller_file=__file__,
        solver=solver,
    )
    discharge_tol = dict(comparison.tolerances.get("discharge", {}))
    uniformity_tol = dict(comparison.tolerances.get("uniformity", {}))
    monotonicity_tol = dict(comparison.tolerances.get("monotonicity", {}))

    assert_metric_below(
        "Relative discharge RMSE",
        comparison.relative_rmse,
        float(discharge_tol["relative_rmse"]),
    )
    assert_metric_below(
        "Relative discharge max abs error",
        comparison.relative_max_error,
        float(discharge_tol["relative_max_error"]),
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(uniformity_tol["row_spread"]),
        unit="m",
    )
    assert_metric_below(
        "Maximum positive discharge increment",
        comparison.max_positive_increment_m3_s,
        float(monotonicity_tol["max_positive_increment_m3_s"]),
        unit="m3/s",
    )
