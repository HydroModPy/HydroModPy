"""SciPy-based nonlinear runtime for the Boussinesq backend.

This backend uses the same physical assembly as the local runtime. The only
thing that changes is the nonlinear driver: instead of a home-grown Newton line
search, we delegate the root solve to ``scipy.optimize.root``.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_dense_semianalytic_regularized_partition_jacobian,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes.execution_common import (
    apply_residual_tolerance,
    build_runtime_result,
    residual_norm_inf,
)
from hydromodpy.solver.boussinesq.runtimes.head_only_common import (
    build_steady_assembly_callback,
    build_transient_assembly_callback,
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
    solve_setup = build_transient_assembly_callback(inputs)

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=float(inputs.dt_seconds),
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(solve_setup.options.regularization_radius),
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        tol_state_update_inf=float(solve_setup.options.tol_state_update_inf),
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance with SciPy root finding."""
    solve_setup = build_steady_assembly_callback(inputs)

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=None,
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(solve_setup.options.regularization_radius),
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        tol_state_update_inf=float(solve_setup.options.tol_state_update_inf),
    )


def _solve_nonlinear_system(
    *,
    assembly_for,
    head_initial_guess_m: np.ndarray,
    mesh,
    dt_seconds: float | None,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
    prescribed_head_m_by_cell: np.ndarray | None,
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
        return np.asarray(assembly.solver_residual, dtype=float)

    def _jacobian(candidate_head: np.ndarray) -> np.ndarray:
        return build_dense_semianalytic_regularized_partition_jacobian(
            mesh,
            np.asarray(candidate_head, dtype=float),
            dt_seconds=dt_seconds,
            regularization_radius=regularization_radius,
            surface_input_rate_m_s=surface_input_rate_m_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
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
    residual_norm = residual_norm_inf(assembly.solver_residual)
    converged, termination_reason = apply_residual_tolerance(
        success=bool(result.success),
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=float(tol_residual_inf),
        termination_reason=str(getattr(result, "message", "") or "").strip(),
    )
    return build_runtime_result(
        head_m=head,
        assembly=assembly,
        converged=converged,
        iterations=int(getattr(result, "nfev", 0)),
        residual_norm_inf_value=residual_norm,
        backend_name="scipy",
        termination_reason=termination_reason,
    )


__all__ = ["solve_steady_problem", "solve_transient_step"]
