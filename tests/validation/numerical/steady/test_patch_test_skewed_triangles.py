"""Patch test: a uniform flow on skewed triangles.

Compared with: the steady head of a uniform flow at every triangle centroid.

A consistent finite-volume flux reproduces a linear head on any cell shape. On
this strip of skewed, non-isosceles triangles MODFLOW 6 with XT3D does, to the
solver closure. The two-point flux of MODFLOW 6 without XT3D and of the
Boussinesq solver does not: their error is recorded against a documented gap.
"""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.numerical.steady.patch_test_skewed_triangles.comparison import (
    run_patch_test_comparison,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow6"),
    [
        pytest.param("modflow6_irregular_tri", True, id="modflow6_irregular_tri"),
        pytest.param("modflow6_irregular_tri_xt3d_off", True, id="modflow6_irregular_tri_xt3d_off"),
        pytest.param("boussinesq_local", False, id="boussinesq_local"),
    ],
)
def test_patch_test_skewed_triangles_reproduces_uniform_flow(
    solver: str, require_modflow6: bool
) -> None:
    """Run one variant and compare its cell heads with the uniform-flow head."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = run_patch_test_comparison(caller_file=__file__, solver=solver)
    record_comparison(comparison)
    heads_tol = dict(comparison.tolerances.get("heads", {}))

    assert_metric_below("Head RMSE", comparison.rms_error, float(heads_tol["rmse"]), unit="m")
    assert_metric_below(
        "Head max abs error",
        comparison.max_error,
        float(heads_tol["max_abs_error"]),
        unit="m",
    )
