"""Rotated horizontal K tensor: uniform flow along a confined strip, plan view.

Compared with: the exact uniform flow of the rotated tensor, far from the ends
of the strip, where the head is a plane with dh/dy = -(K_xy / K_yy) dh/dx and
the flow along the strip is K11 K22 / K_yy times the gradient and the section.

The flow sets K, K22 and ANGLE1 through ``[flow.param]``, HydroModPy writes
them to the NPF package with XT3D, and the run stores the heads and the
constant-head flows. A sign error on ANGLE1 flips the slope across the strip,
an axis error changes its size, and the two-point flux without XT3D leaves it
at zero: each moves the heads by a share of the 0.56 m drop across the strip.
The mirrored variant runs ANGLE1 = -30 deg against its own reference.
"""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import (
    assert_metric_below,
    record_comparison,
    record_scale,
    record_series,
)
from validation_cases.analytical.steady.k_tensor_rotated_plan_2d.comparison import (
    run_rotated_plan_comparison,
)

NOT_APPLICABLE = {
    "modflow_nwt": "MODFLOW-NWT reads K and Kv only: the load refuses K22 and the angles of the K tensor for it.",
    "boussinesq": "The Boussinesq solver takes a scalar K: the load refuses K22 and the angles of the K tensor for it.",
    "boussinesq_local": "The Boussinesq solver takes a scalar K: the load refuses K22 and the angles of the K tensor for it.",
    "modflow6_irregular_tri": "Not run: the case checks the tensor conventions on the structured grid. XT3D carries a linear head on triangles too (patch test), but this strip has no triangle variant.",
    "modflow6_voronoi": "Not run: the case checks the tensor conventions on the structured grid. A Voronoi variant of this strip is not set up.",
}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow6", id="modflow6"),
        pytest.param("modflow6_mirrored", id="modflow6_mirrored"),
    ],
)
def test_k_tensor_rotated_plan_2d_carries_the_exact_uniform_flow(solver: str) -> None:
    """Run one ANGLE1 variant and compare the window heads and the end flows."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_rotated_plan_comparison(caller_file=__file__, solver=solver)
    fit = comparison.fit
    assert comparison.tensor_input_mismatch <= 1e-12, (
        "The run stored another K tensor than the case declares: largest gap "
        f"{comparison.tensor_input_mismatch:.3g}."
    )
    record_comparison(comparison)
    record_scale(fit.head_drop_across, "head drop across the strip in the window", "m")
    record_series(
        "Head across the strip at its middle",
        comparison.profile_y_m,
        comparison.profile_reference,
        comparison.profile_numerical,
        x_label="y (m)",
        y_label="head (m)",
    )
    tol = dict(comparison.tolerances["uniform_flow"])

    assert_metric_below(
        "Gradient direction relative error",
        fit.gradient_ratio_error,
        float(tol["gradient_direction_relative_error"]),
    )
    assert_metric_below(
        "Head max abs error", fit.head_max_error, float(tol["head_max_abs_error"]), unit="m"
    )
    assert_metric_below(
        "End flow relative error", fit.flow_error, float(tol["end_flow_relative_error"])
    )
