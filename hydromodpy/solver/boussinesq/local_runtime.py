"""Local implicit runtime for the Boussinesq backend."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


@dataclass(frozen=True)
class LocalStepSolveResult:
    """Result of one local fully implicit time step."""

    head_m: np.ndarray
    assembly: BoussinesqAssembly
    converged: bool
    iterations: int
    residual_norm_inf: float


def _fd_jacobian(
    residual_fn,
    head_m: np.ndarray,
    residual0: np.ndarray,
    *,
    rel_step: float,
) -> np.ndarray:
    """Build one dense finite-difference Jacobian for the local Newton solve."""
    head = np.asarray(head_m, dtype=float)
    residual_base = np.asarray(residual0, dtype=float)
    n_cells = int(head.size)
    jacobian = np.zeros((n_cells, n_cells), dtype=float)
    for col in range(n_cells):
        step = rel_step * max(1.0, abs(float(head[col])))
        perturbed = head.copy()
        perturbed[col] += step
        residual_perturbed = np.asarray(residual_fn(perturbed), dtype=float)
        jacobian[:, col] = (residual_perturbed - residual_base) / step
    return jacobian


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
) -> LocalStepSolveResult:
    """Solve one nonlinear backward-Euler step by dense Newton iterations."""
    if float(dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")
    head_prev = np.asarray(head_prev_m, dtype=float)
    head = (
        head_prev.copy()
        if head_initial_guess_m is None
        else np.asarray(head_initial_guess_m, dtype=float).copy()
    )

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_transient_residual(
            mesh,
            head_m=candidate_head,
            head_prev_m=head_prev,
            dt_seconds=float(dt_seconds),
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            imposed_head_m_by_edge=imposed_head_m_by_edge,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
            regularization_radius=float(regularization_radius),
        )

    return _solve_nonlinear_system(
        assembly_for=_assembly_for,
        head_initial_guess_m=head,
        max_iterations=max_iterations,
        tol_residual_inf=tol_residual_inf,
        fd_rel_step=fd_rel_step,
        min_damping=min_damping,
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
) -> LocalStepSolveResult:
    """Solve one nonlinear steady-state system by dense Newton iterations."""
    head = np.asarray(head_initial_guess_m, dtype=float).copy()

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_steady_residual(
            mesh,
            head_m=candidate_head,
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            imposed_head_m_by_edge=imposed_head_m_by_edge,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
            regularization_radius=float(regularization_radius),
        )

    return _solve_nonlinear_system(
        assembly_for=_assembly_for,
        head_initial_guess_m=head,
        max_iterations=max_iterations,
        tol_residual_inf=tol_residual_inf,
        fd_rel_step=fd_rel_step,
        min_damping=min_damping,
    )


def _solve_nonlinear_system(
    *,
    assembly_for,
    head_initial_guess_m: np.ndarray,
    max_iterations: int,
    tol_residual_inf: float,
    fd_rel_step: float,
    min_damping: float,
) -> LocalStepSolveResult:
    """Run the shared dense Newton loop for one head-only nonlinear system."""
    head = np.asarray(head_initial_guess_m, dtype=float).copy()
    assembly = assembly_for(head)
    residual = assembly.residual_m3_s
    residual_norm = float(np.linalg.norm(residual, ord=np.inf))
    if residual_norm <= float(tol_residual_inf):
        return LocalStepSolveResult(
            head_m=head,
            assembly=assembly,
            converged=True,
            iterations=0,
            residual_norm_inf=residual_norm,
        )

    for iteration in range(1, int(max_iterations) + 1):
        jacobian = _fd_jacobian(
            lambda candidate: assembly_for(candidate).residual_m3_s,
            head,
            residual,
            rel_step=float(fd_rel_step),
        )
        try:
            delta = np.linalg.solve(jacobian, -residual)
        except np.linalg.LinAlgError:
            break

        damping = 1.0
        accepted = False
        while damping >= float(min_damping):
            candidate_head = head + damping * delta
            candidate_assembly = assembly_for(candidate_head)
            candidate_residual = candidate_assembly.residual_m3_s
            candidate_norm = float(np.linalg.norm(candidate_residual, ord=np.inf))
            if candidate_norm < residual_norm or damping <= float(min_damping):
                head = candidate_head
                assembly = candidate_assembly
                residual = candidate_residual
                residual_norm = candidate_norm
                accepted = True
                break
            damping *= 0.5

        if not accepted:
            break
        if residual_norm <= float(tol_residual_inf):
            return LocalStepSolveResult(
                head_m=head,
                assembly=assembly,
                converged=True,
                iterations=iteration,
                residual_norm_inf=residual_norm,
            )

    return LocalStepSolveResult(
        head_m=head,
        assembly=assembly,
        converged=False,
        iterations=int(max_iterations),
        residual_norm_inf=residual_norm,
    )


__all__ = ["LocalStepSolveResult", "solve_backward_euler_step", "solve_steady_state"]
