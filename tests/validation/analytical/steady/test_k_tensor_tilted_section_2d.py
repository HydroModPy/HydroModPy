"""Tilted K tensor: uniform flow along a confined layered section.

Compared with: the exact uniform flow of the tilted tensor, far from the ends
of the section, where the head is a plane with dh/dz = -(K_xz / K_zz) dh/dx and
the flow along the section is K11 K33 / K_zz times the gradient and the
cross-section.

The flow sets K, Kv (K33) and ANGLE2 through ``[flow.param]``, HydroModPy
writes them to the NPF package with ANGLE1 and ANGLE3 at zero and XT3D on, and
the run stores the heads of the five layers and the constant-head flows.
MODFLOW 6 turns K11 from +x toward +z for a positive ANGLE2, so the head rises
with elevation when the flow runs east. The opposite sign flips the vertical
head gradient, and an axis error or the two-point flux without XT3D changes or
removes it: each moves the heads by a share of the 0.29 m drop over the depth.
The mirrored variant runs ANGLE2 = -20 deg against its own reference.
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
from validation_cases.analytical.steady.k_tensor_tilted_section_2d.comparison import (
    run_tilted_section_comparison,
)

NOT_APPLICABLE = {
    "modflow_nwt": "MODFLOW-NWT reads K and Kv only: the load refuses the angles of the K tensor for it.",
    "boussinesq": "The Boussinesq solver is a single-layer vertically integrated model with a scalar K: the load refuses the angles of the K tensor for it.",
    "boussinesq_local": "The Boussinesq solver is a single-layer vertically integrated model with a scalar K: the load refuses the angles of the K tensor for it.",
    "modflow6_irregular_tri": "The section is one row of cells: the tensor tilts in the vertical plane, which a triangle mesh of the plan view does not change.",
    "modflow6_voronoi": "The section is one row of cells: the tensor tilts in the vertical plane, which a Voronoi mesh of the plan view does not change.",
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
def test_k_tensor_tilted_section_2d_carries_the_exact_uniform_flow(solver: str) -> None:
    """Run one ANGLE2 variant and compare the window heads and the end flows."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_tilted_section_comparison(caller_file=__file__, solver=solver)
    fit = comparison.fit
    assert comparison.tensor_input_mismatch <= 1e-12, (
        "The run stored another K tensor than the case declares: largest gap "
        f"{comparison.tensor_input_mismatch:.3g}."
    )
    record_comparison(comparison)
    record_scale(fit.head_drop_across, "head drop over the depth of the window", "m")
    record_series(
        "Head against elevation at the middle of the section",
        comparison.profile_z_m,
        comparison.profile_reference,
        comparison.profile_numerical,
        x_label="elevation (m)",
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
