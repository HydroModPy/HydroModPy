"""Validate PETSc Boussinesq variants on the steady Dupuit fixed-head case."""

from __future__ import annotations

import platform

import pytest

from tests.validation.helpers import assert_metric_below
from validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison import (
    run_dupuit_fixed_head_comparison,
)


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


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
    _require_linux_petsc4py()

    comparison = run_dupuit_fixed_head_comparison(
        caller_file=__file__,
        solver=solver,
    )
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
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.petsc
def test_dupuit_fixed_head_petsc_ts_vi_obstacle_reaches_reference_profile() -> None:
    """Validate TS VI obstacle against the existing Dupuit fixed-head profile."""
    _require_linux_petsc4py()

    comparison = run_dupuit_fixed_head_comparison(
        caller_file=__file__,
        solver="petsc_ts_vi_obstacle",
    )
    tolerances = dict(comparison.tolerances)

    assert comparison.solver == "petsc_ts_vi_obstacle"
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
