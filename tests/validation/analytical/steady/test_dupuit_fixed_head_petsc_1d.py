"""Validate PETSc Boussinesq variants on the steady Dupuit fixed-head case."""

from __future__ import annotations

import platform

import pytest

from tests.validation.helpers import assert_metric_below, record_comparison
from tests.validation.helpers.petsc import require_linux_petsc4py
from validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison import (
    run_dupuit_fixed_head_comparison,
)

NOT_APPLICABLE = {
    "modflow_nwt": "The file runs the Boussinesq surface-interaction closures (regularized partition, complementarity, VI obstacle) selected through runtime_backend = petsc, which have no MODFLOW counterpart. The same Dupuit profile runs on NWT in test_dupuit_fixed_head_1d.py.",
    "modflow6": "The file runs the Boussinesq surface-interaction closures (regularized partition, complementarity, VI obstacle) selected through runtime_backend = petsc, which have no MODFLOW counterpart. The same Dupuit profile runs on MF6 in test_dupuit_fixed_head_1d.py.",
    "modflow6_irregular_tri": "The file runs the Boussinesq surface-interaction closures (regularized partition, complementarity, VI obstacle) selected through runtime_backend = petsc, which have no MODFLOW counterpart. The same Dupuit profile runs on MF6 triangles in test_dupuit_fixed_head_1d.py.",
    "modflow6_voronoi": "The file runs the Boussinesq surface-interaction closures (regularized partition, complementarity, VI obstacle) selected through runtime_backend = petsc, which have no MODFLOW counterpart. A MF6 Voronoi run of this Dupuit profile belongs in test_dupuit_fixed_head_1d.py, not here.",
    "boussinesq_local": "The complementarity and VI obstacle closures exist only in the PETSc engine; the local engine supports head_only_regularized_partition only. The regularized-partition profile on the default engine is already test_dupuit_fixed_head_1d[boussinesq_local].",
}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.petsc
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("petsc_partition", id="petsc_partition"),
        pytest.param("petsc", id="petsc_complementarity"),
    ],
)
def test_dupuit_fixed_head_petsc_variants_match_reference_profile(
    solver: str,
) -> None:
    """Run the small analytical PETSc smoke case and assert physical metrics."""
    require_linux_petsc4py()

    comparison = run_dupuit_fixed_head_comparison(
        caller_file=__file__,
        solver=solver,
    )
    record_comparison(comparison)
    tolerances = dict(comparison.tolerances)

    assert_metric_below(
        "Head-profile RMSE",
        comparison.rms_error,
        float(tolerances["rms_error_max"]),
        unit="m",
    )
    assert_metric_below(
        "Head-profile max abs error",
        comparison.max_error,
        float(tolerances["max_error_max"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(tolerances["row_spread_max"]),
        unit="m",
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.petsc
def test_dupuit_fixed_head_petsc_vi_obstacle_reaches_reference_profile() -> None:
    """Validate steady VI obstacle against the existing Dupuit fixed-head profile."""
    require_linux_petsc4py()

    comparison = run_dupuit_fixed_head_comparison(
        caller_file=__file__,
        solver="petsc_vi_obstacle",
    )
    record_comparison(comparison)
    tolerances = dict(comparison.tolerances)

    assert comparison.solver == "petsc_vi_obstacle"
    assert_metric_below(
        "Head-profile RMSE",
        comparison.rms_error,
        float(tolerances["rms_error_max"]),
        unit="m",
    )
    assert_metric_below(
        "Head-profile max abs error",
        comparison.max_error,
        float(tolerances["max_error_max"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(tolerances["row_spread_max"]),
        unit="m",
    )
