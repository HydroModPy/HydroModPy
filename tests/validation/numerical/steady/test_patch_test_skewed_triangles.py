"""Patch test: a uniform flow on skewed triangles.

Compared with: the steady head of a uniform flow at every triangle centroid.

A consistent finite-volume flux reproduces a linear head on any cell shape. On
this strip of skewed, non-isosceles triangles MODFLOW 6 with XT3D does, to the
solver closure, and so does MODFLOW 6 on the Voronoi dual of the same nodes and on
a Voronoi mesh generated on the same strip: the cells are orthogonal to their
faces (the face between two cells bisects their nodes), so the two-point flux of
a uniform gradient is exact. The
two-point flux between triangle centroids, in MODFLOW 6 without XT3D and in the
Boussinesq solver (default local engine and PETSc engine, which assemble the same
residual), does not: their error is recorded against a documented gap.
"""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_comparison
from validation_cases.numerical.steady.patch_test_skewed_triangles.comparison import (
    run_patch_test_comparison,
)

NOT_APPLICABLE = {
    "modflow_nwt": "MODFLOW-NWT builds a structured grid of axis-aligned rectangles and ignores a runtime mesh: it cannot hold the skewed triangles of this strip.",
    "modflow6": "The structured MODFLOW 6 grid is axis-aligned rectangles with centres normal to the shared faces: no skewed cells. Its skewed-triangle runs are the triangle and Voronoi columns.",
}


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    ("solver", "require_modflow6"),
    [
        pytest.param("modflow6_irregular_tri", True, id="modflow6_irregular_tri"),
        pytest.param("modflow6_irregular_tri_xt3d_off", True, id="modflow6_irregular_tri_xt3d_off"),
        pytest.param("modflow6_voronoi", True, id="modflow6_voronoi"),
        pytest.param("modflow6_voronoi_generated", True, id="modflow6_voronoi_generated"),
        pytest.param("boussinesq", False, marks=pytest.mark.petsc, id="boussinesq"),
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
