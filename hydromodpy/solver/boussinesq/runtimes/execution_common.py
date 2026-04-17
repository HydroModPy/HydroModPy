"""Common runtime-execution helpers shared by Boussinesq backends."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.runtime_contract import RuntimeSolveResult


def residual_norm_inf(residual_m3_s: np.ndarray) -> float:
    """Return the infinity norm of one residual vector as a plain float."""
    return float(np.linalg.norm(np.asarray(residual_m3_s, dtype=float), ord=np.inf))


def apply_residual_tolerance(
    *,
    success: bool,
    residual_norm_inf_value: float,
    tol_residual_inf: float,
    termination_reason: str,
    residual_label: str = "residual_inf",
) -> tuple[bool, str]:
    """Refine a backend success flag with the shared residual-tolerance contract."""
    converged = bool(success) and residual_norm_inf_value <= float(tol_residual_inf)
    if bool(success) and not converged:
        reason = str(termination_reason or "").strip()
        if reason:
            reason = (
                f"{reason}; {residual_label}={residual_norm_inf_value:.3e} still exceeds "
                f"tol_residual_inf={float(tol_residual_inf):.3e}"
            )
        else:
            reason = (
                f"{residual_label}={residual_norm_inf_value:.3e} still exceeds "
                f"tol_residual_inf={float(tol_residual_inf):.3e}"
            )
        return converged, reason
    return converged, str(termination_reason)


def build_runtime_result(
    *,
    head_m: np.ndarray,
    assembly,
    converged: bool,
    iterations: int,
    residual_norm_inf_value: float,
    backend_name: str,
    termination_reason: str,
) -> RuntimeSolveResult:
    """Build the canonical runtime result payload."""
    return RuntimeSolveResult(
        head_m=np.asarray(head_m, dtype=float),
        assembly=assembly,
        converged=bool(converged),
        iterations=int(iterations),
        residual_norm_inf=float(residual_norm_inf_value),
        backend_name=str(backend_name),
        termination_reason=str(termination_reason),
    )


__all__ = [
    "apply_residual_tolerance",
    "build_runtime_result",
    "residual_norm_inf",
]
