"""In-process nonlinear runtime for the Boussinesq backend.

This backend is intentionally simple and transparent:

- the residual is assembled in pure NumPy,
- the Jacobian is approximated by dense finite differences,
- the nonlinear solve uses a damped Newton loop.

It is therefore not the fastest option, but it is the easiest one to inspect
when validating the physics or debugging convergence problems.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.jacobian_fd import build_dense_fd_jacobian
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one implicit transient step from the normalized runtime contract.

    This function only translates the generic runtime inputs into one residual
    callback. The actual Newton loop is shared in ``_solve_nonlinear_system``.
    """
    if float(inputs.dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    head_prev = np.asarray(inputs.head_prev_m, dtype=float)
    head = (
        head_prev.copy()
        if inputs.head_initial_guess_m is None
        else np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    )
    options = inputs.options

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_transient_residual(
            inputs.mesh,
            head_m=candidate_head,
            head_prev_m=head_prev,
            dt_seconds=float(inputs.dt_seconds),
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            imposed_head_m_by_edge=inputs.imposed_head_m_by_edge,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(options.regularization_radius),
        )

    return _solve_nonlinear_system(
        assembly_for=_assembly_for,
        head_initial_guess_m=head,
        max_iterations=int(options.max_iterations),
        tol_residual_inf=float(options.tol_residual_inf),
        fd_rel_step=float(options.fd_rel_step),
        min_damping=float(options.min_damping),
        backend_name="local",
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance from the normalized runtime contract."""
    head = np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    options = inputs.options

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_steady_residual(
            inputs.mesh,
            head_m=candidate_head,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            imposed_head_m_by_edge=inputs.imposed_head_m_by_edge,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(options.regularization_radius),
        )

    return _solve_nonlinear_system(
        assembly_for=_assembly_for,
        head_initial_guess_m=head,
        max_iterations=int(options.max_iterations),
        tol_residual_inf=float(options.tol_residual_inf),
        fd_rel_step=float(options.fd_rel_step),
        min_damping=float(options.min_damping),
        backend_name="local",
    )


def solve_backward_euler_step(
    mesh: BoussinesqMesh,
    *,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    head_initial_guess_m: np.ndarray | None = None,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    imposed_head_m_by_edge: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
    max_iterations: int = 20,
    tol_residual_inf: float = 1.0e-9,
    fd_rel_step: float = 1.0e-7,
    min_damping: float = 1.0e-4,
) -> RuntimeSolveResult:
    """Compatibility wrapper around :func:`solve_transient_step`.

    The explicit argument list is convenient in tests and notebooks, while the
    runtime contract remains the internal interface used by the solver driver.
    """
    return solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray(head_prev_m, dtype=float),
            dt_seconds=float(dt_seconds),
            head_initial_guess_m=head_initial_guess_m,
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            imposed_head_m_by_edge=imposed_head_m_by_edge,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
            options=NonlinearRuntimeOptions(
                regularization_radius=float(regularization_radius),
                max_iterations=int(max_iterations),
                tol_residual_inf=float(tol_residual_inf),
                fd_rel_step=float(fd_rel_step),
                min_damping=float(min_damping),
            ),
        )
    )


def solve_steady_state(
    mesh: BoussinesqMesh,
    *,
    head_initial_guess_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    imposed_head_m_by_edge: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
    max_iterations: int = 20,
    tol_residual_inf: float = 1.0e-9,
    fd_rel_step: float = 1.0e-7,
    min_damping: float = 1.0e-4,
) -> RuntimeSolveResult:
    """Compatibility wrapper around :func:`solve_steady_problem`."""
    return solve_steady_problem(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray(head_initial_guess_m, dtype=float),
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            imposed_head_m_by_edge=imposed_head_m_by_edge,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
            options=NonlinearRuntimeOptions(
                regularization_radius=float(regularization_radius),
                max_iterations=int(max_iterations),
                tol_residual_inf=float(tol_residual_inf),
                fd_rel_step=float(fd_rel_step),
                min_damping=float(min_damping),
            ),
        )
    )


def _solve_nonlinear_system(
    *,
    assembly_for,
    head_initial_guess_m: np.ndarray,
    max_iterations: int,
    tol_residual_inf: float,
    fd_rel_step: float,
    min_damping: float,
    backend_name: str,
) -> RuntimeSolveResult:
    """Run the shared dense Newton loop for one head-only nonlinear system.

    Every Newton iteration follows the same sequence:

    1. assemble the nonlinear residual at the current iterate,
    2. build a dense finite-difference Jacobian,
    3. solve the linearized system for the Newton increment,
    4. damp that increment until the residual decreases.
    """
    head = np.asarray(head_initial_guess_m, dtype=float).copy()
    assembly = assembly_for(head)
    residual = assembly.residual_m3_s
    residual_norm = float(np.linalg.norm(residual, ord=np.inf))
    if residual_norm <= float(tol_residual_inf):
        return RuntimeSolveResult(
            head_m=head,
            assembly=assembly,
            converged=True,
            iterations=0,
            residual_norm_inf=residual_norm,
            backend_name=str(backend_name),
            termination_reason="initial residual already satisfies tol_residual_inf",
        )

    termination_reason = "dense Newton max_iterations reached before tol_residual_inf"
    for iteration in range(1, int(max_iterations) + 1):
        # Rebuild the Jacobian at each iterate so the linearization stays
        # consistent with the current nonlinear state.
        jacobian = build_dense_fd_jacobian(
            lambda candidate: assembly_for(candidate).residual_m3_s,
            head,
            residual,
            rel_step=float(fd_rel_step),
        )
        try:
            delta = np.linalg.solve(jacobian, -residual)
        except np.linalg.LinAlgError:
            termination_reason = "dense Newton Jacobian solve failed"
            break

        damping = 1.0
        accepted = False
        while damping >= float(min_damping):
            candidate_head = head + damping * delta
            candidate_assembly = assembly_for(candidate_head)
            candidate_residual = candidate_assembly.residual_m3_s
            candidate_norm = float(np.linalg.norm(candidate_residual, ord=np.inf))
            # Accept the step as soon as it decreases the residual; otherwise
            # backtrack by halving the damping factor.
            if candidate_norm < residual_norm or damping <= float(min_damping):
                head = candidate_head
                assembly = candidate_assembly
                residual = candidate_residual
                residual_norm = candidate_norm
                accepted = True
                break
            damping *= 0.5

        if not accepted:
            termination_reason = "dense Newton line search failed to reduce the residual"
            break
        if residual_norm <= float(tol_residual_inf):
            return RuntimeSolveResult(
                head_m=head,
                assembly=assembly,
                converged=True,
                iterations=iteration,
                residual_norm_inf=residual_norm,
                backend_name=str(backend_name),
                termination_reason="dense Newton residual tolerance reached",
            )

    return RuntimeSolveResult(
        head_m=head,
        assembly=assembly,
        converged=False,
        iterations=int(max_iterations),
        residual_norm_inf=residual_norm,
        backend_name=str(backend_name),
        termination_reason=termination_reason,
    )

LocalStepSolveResult = RuntimeSolveResult

__all__ = [
    "LocalStepSolveResult",
    "solve_backward_euler_step",
    "solve_steady_problem",
    "solve_steady_state",
    "solve_transient_step",
]
