"""Shared damped-Newton template for head-only Boussinesq runtimes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly
from hydromodpy.solver.boussinesq.runtime_contract import RuntimeSolveResult
from hydromodpy.solver.boussinesq.runtimes.execution_common import (
    build_runtime_result,
    residual_norm_inf,
)

HeadOnlyAssemblyCallback = Callable[[np.ndarray], BoussinesqAssembly]
NewtonJacobianBuilder = Callable[
    [np.ndarray, BoussinesqAssembly, np.ndarray, float, float, int],
    Any,
]
NewtonLinearSolver = Callable[[Any, np.ndarray, float, float], np.ndarray]
NewtonLogStart = Callable[[float, float, int], None]
NewtonLogIteration = Callable[[int, float, float], None]


def _noop_log_start(
    residual_norm_inf_value: float,
    tol_residual_inf: float,
    max_iterations: int,
) -> None:
    """Default no-op hook used by backends that do not expose Newton logging."""


def _noop_log_iteration(
    iteration: int,
    residual_norm_inf_value: float,
    damping: float,
) -> None:
    """Default no-op per-iteration hook used by quiet runtimes."""


def _newton_loop_template(
    *,
    assembly_for: HeadOnlyAssemblyCallback,
    head_initial_guess_m: np.ndarray,
    max_iterations: int,
    tol_residual_inf: float,
    min_damping: float,
    backend_name: str,
    newton_label: str,
    build_jacobian: NewtonJacobianBuilder,
    solve_linear_system: NewtonLinearSolver,
    log_start: NewtonLogStart = _noop_log_start,
    log_iteration: NewtonLogIteration = _noop_log_iteration,
) -> RuntimeSolveResult:
    """Run the shared damped Newton loop.

    The dense and sparse head-only runtimes differ mainly in how they build the
    Jacobian and solve the resulting linear system. The surrounding nonlinear
    control flow stays identical and lives here.
    """

    head = np.asarray(head_initial_guess_m, dtype=float).copy()
    assembly = assembly_for(head)
    residual = np.asarray(assembly.residual_m3_s, dtype=float)
    residual_norm = residual_norm_inf(residual)
    initial_residual_norm = residual_norm
    if residual_norm <= float(tol_residual_inf):
        return build_runtime_result(
            head_m=head,
            assembly=assembly,
            converged=True,
            iterations=0,
            residual_norm_inf_value=residual_norm,
            backend_name=str(backend_name),
            termination_reason="initial residual already satisfies tol_residual_inf",
        )

    log_start(residual_norm, float(tol_residual_inf), int(max_iterations))
    termination_reason = f"{newton_label} Newton max_iterations reached before tol_residual_inf"
    for iteration in range(1, int(max_iterations) + 1):
        jacobian = build_jacobian(
            head,
            assembly,
            residual,
            residual_norm,
            initial_residual_norm,
            iteration,
        )
        try:
            delta = np.asarray(
                solve_linear_system(
                    jacobian,
                    residual,
                    residual_norm,
                    initial_residual_norm,
                ),
                dtype=float,
            ).reshape(-1)
        except RuntimeError:
            termination_reason = f"{newton_label} Newton Jacobian solve failed"
            break

        damping = 1.0
        accepted = False
        while damping >= float(min_damping):
            candidate_head = head + damping * delta
            candidate_assembly = assembly_for(candidate_head)
            candidate_residual = np.asarray(candidate_assembly.residual_m3_s, dtype=float)
            candidate_norm = residual_norm_inf(candidate_residual)
            if candidate_norm < residual_norm or damping <= float(min_damping):
                head = candidate_head
                assembly = candidate_assembly
                residual = candidate_residual
                residual_norm = candidate_norm
                accepted = True
                break
            damping *= 0.5

        log_iteration(iteration, residual_norm, damping)
        if not accepted:
            termination_reason = f"{newton_label} Newton line search failed to reduce the residual"
            break
        if residual_norm <= float(tol_residual_inf):
            return build_runtime_result(
                head_m=head,
                assembly=assembly,
                converged=True,
                iterations=iteration,
                residual_norm_inf_value=residual_norm,
                backend_name=str(backend_name),
                termination_reason=f"{newton_label} Newton residual tolerance reached",
            )

    return build_runtime_result(
        head_m=head,
        assembly=assembly,
        converged=False,
        iterations=int(max_iterations),
        residual_norm_inf_value=residual_norm,
        backend_name=str(backend_name),
        termination_reason=termination_reason,
    )


__all__ = ["_newton_loop_template"]
