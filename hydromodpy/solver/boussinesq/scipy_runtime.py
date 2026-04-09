"""SciPy-based nonlinear runtime for the Boussinesq backend.

This backend uses the same physical assembly as the local runtime. The only
thing that changes is the nonlinear driver: instead of a home-grown Newton line
search, we delegate the root solve to ``scipy.optimize.root``.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.jacobian_semianalytic import (
    build_dense_semianalytic_regularized_partition_jacobian,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)


def _require_scipy_optimize():
    """Import SciPy lazily so choosing ``runtime_backend='scipy'`` stays explicit."""
    try:
        from scipy import optimize as scipy_optimize
    except Exception as exc:  # pragma: no cover - depends on optional import state
        raise RuntimeError(
            "Boussinesq runtime_backend='scipy' requires scipy to be installed."
        ) from exc
    return scipy_optimize


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one transient implicit step with SciPy root finding."""
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
        mesh=inputs.mesh,
        dt_seconds=float(inputs.dt_seconds),
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(options.regularization_radius),
        imposed_head_m_by_edge=inputs.imposed_head_m_by_edge,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(options.max_iterations),
        tol_residual_inf=float(options.tol_residual_inf),
        tol_state_update_inf=float(options.tol_state_update_inf),
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance with SciPy root finding."""
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
        mesh=inputs.mesh,
        dt_seconds=None,
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(options.regularization_radius),
        imposed_head_m_by_edge=inputs.imposed_head_m_by_edge,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(options.max_iterations),
        tol_residual_inf=float(options.tol_residual_inf),
        tol_state_update_inf=float(options.tol_state_update_inf),
    )


def _solve_nonlinear_system(
    *,
    assembly_for,
    head_initial_guess_m: np.ndarray,
    mesh,
    dt_seconds: float | None,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
    imposed_head_m_by_edge: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    max_iterations: int,
    tol_residual_inf: float,
    tol_state_update_inf: float,
) -> RuntimeSolveResult:
    """Run one SciPy root solve around the NumPy assembly callbacks.

    SciPy only sees the head vector and residual/Jacobian callbacks. All
    Boussinesq-specific physics stays inside the assembly functions.
    """
    scipy_optimize = _require_scipy_optimize()
    head0 = np.asarray(head_initial_guess_m, dtype=float).reshape(-1)

    def _residual(candidate_head: np.ndarray) -> np.ndarray:
        assembly = assembly_for(np.asarray(candidate_head, dtype=float))
        return np.asarray(assembly.residual_m3_s, dtype=float)

    def _jacobian(candidate_head: np.ndarray) -> np.ndarray:
        return build_dense_semianalytic_regularized_partition_jacobian(
            mesh,
            np.asarray(candidate_head, dtype=float),
            dt_seconds=dt_seconds,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
            imposed_head_m_by_edge=imposed_head_m_by_edge,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
        )

    result = scipy_optimize.root(
        _residual,
        head0,
        jac=_jacobian,
        method="hybr",
        options={
            "xtol": float(tol_state_update_inf),
            "maxfev": max(int(max_iterations), 1) * max(int(head0.size), 1) * 4,
        },
    )

    head = np.asarray(result.x, dtype=float).copy()
    # Reassemble once at the accepted state so the returned fluxes and residual
    # are fully consistent with the final head vector.
    assembly = assembly_for(head)
    residual_norm_inf = float(np.linalg.norm(assembly.residual_m3_s, ord=np.inf))
    converged = bool(result.success) and residual_norm_inf <= float(tol_residual_inf)
    termination_reason = str(getattr(result, "message", "") or "").strip()
    if bool(result.success) and not converged:
        termination_reason = (
            f"{termination_reason}; residual_inf={residual_norm_inf:.3e} still exceeds "
            f"tol_residual_inf={float(tol_residual_inf):.3e}"
        ).strip("; ")
    return RuntimeSolveResult(
        head_m=head,
        assembly=assembly,
        converged=converged,
        iterations=int(getattr(result, "nfev", 0)),
        residual_norm_inf=residual_norm_inf,
        backend_name="scipy",
        termination_reason=termination_reason,
    )


__all__ = ["solve_steady_problem", "solve_transient_step"]
