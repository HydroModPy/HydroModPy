"""Validate the linearized unconfined transient cases against their analytical references.

This driver folds five sibling 1D linearized-unconfined transient benchmarks into one
parametrized suite. Each scenario keeps its own forcing (via its own launcher comparison
function) and its own tolerances (read from the per-case tolerance TOML through the
comparison payload, including the per-scenario cross-row spread envelope documented in
``tests/TOLERANCES.md`` rows 25-29).
"""

from __future__ import annotations

import platform
from collections.abc import Callable
from typing import Any

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import (
    assert_profile_metrics,
    assert_space_time_metrics,
)
from validation_cases.analytical.transient.linearized_unconfined_boundary_piecewise_1d.comparison import (
    run_linearized_unconfined_boundary_piecewise_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.comparison import (
    run_linearized_unconfined_boundary_step_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_periodic_1d.comparison import (
    run_linearized_unconfined_recharge_periodic_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d.comparison import (
    run_linearized_unconfined_recharge_step_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_deep_1d.comparison import (
    run_linearized_unconfined_recharge_step_deep_comparison,
)

ComparisonRunner = Callable[..., Any]

# One launcher comparison function per scenario. Each function pins its own forcing
# (recharge step, periodic recharge, piecewise boundary, boundary step, deep aquifer) and
# loads its own tolerance TOML, so no tolerance is shared across scenarios.
SCENARIO_RUNNERS: dict[str, ComparisonRunner] = {
    "recharge_step": run_linearized_unconfined_recharge_step_comparison,
    "recharge_periodic": run_linearized_unconfined_recharge_periodic_comparison,
    "boundary_piecewise": run_linearized_unconfined_boundary_piecewise_comparison,
    "boundary_step": run_linearized_unconfined_boundary_step_comparison,
    "recharge_step_deep": run_linearized_unconfined_recharge_step_deep_comparison,
}

# Scenarios that additionally exercise the Boussinesq PETSc obstacle solvers.
PETSC_SCENARIOS: tuple[str, ...] = ("recharge_step", "boundary_step")


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize(
    "scenario",
    [pytest.param(name, id=name) for name in SCENARIO_RUNNERS],
)
@pytest.mark.parametrize(
    ("solver", "require_modflow", "require_modflow6"),
    [
        pytest.param("modflow_nwt", True, False, id="modflow_nwt"),
        pytest.param("modflow6", False, True, id="modflow6"),
        pytest.param("modflow6_irregular_tri", False, True, id="modflow6_irregular_tri"),
        pytest.param("boussinesq", False, False, id="boussinesq"),
    ],
)
def test_linearized_unconfined_transient_1d_matches_reference_profiles(
    scenario: str,
    solver: str,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Run one scenario through one solver and compare the full transient profile matrix."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    comparison = SCENARIO_RUNNERS[scenario](caller_file=__file__, solver=solver)

    assert_space_time_metrics(comparison)
    assert_profile_metrics(comparison)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.petsc
@pytest.mark.parametrize(
    "scenario",
    [pytest.param(name, id=name) for name in PETSC_SCENARIOS],
)
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("petsc_ts_vi_obstacle", id="petsc_ts_vi_obstacle"),
        pytest.param("petsc_vi_obstacle", id="petsc_vi_obstacle"),
    ],
)
def test_linearized_unconfined_transient_1d_petsc_obstacle_matches_reference_profiles(
    scenario: str,
    solver: str,
) -> None:
    """Run one scenario through a PETSc obstacle solver and compare the profile matrix."""
    _require_linux_petsc4py()

    comparison = SCENARIO_RUNNERS[scenario](caller_file=__file__, solver=solver)

    assert comparison.result.solver_name == solver
    assert_space_time_metrics(comparison)
    assert_profile_metrics(comparison)
