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

from hydromodpy.solver.boussinesq.jacobian.fd import build_dense_fd_jacobian
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes.head_only_common import (
    build_steady_assembly_callback,
    build_transient_assembly_callback,
)
from hydromodpy.solver.boussinesq.runtimes.newton_common import (
    _newton_loop_template,
)


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one implicit transient step from the normalized runtime contract.

    This function only translates the generic runtime inputs into one residual
    callback. The actual Newton loop is shared in ``_solve_nonlinear_system``.
    """
    solve_setup = build_transient_assembly_callback(inputs)

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        fd_rel_step=float(solve_setup.options.fd_rel_step),
        min_damping=float(solve_setup.options.min_damping),
        backend_name="local",
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance from the normalized runtime contract."""
    solve_setup = build_steady_assembly_callback(inputs)

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        fd_rel_step=float(solve_setup.options.fd_rel_step),
        min_damping=float(solve_setup.options.min_damping),
        backend_name="local",
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
    """Run the dense Newton loop by plugging dense callbacks into the template."""

    def _build_dense_jacobian(
        head_m: np.ndarray,
        _assembly,
        residual_m3_s: np.ndarray,
        _residual_norm_inf: float,
        _initial_residual_norm_inf: float,
        _iteration: int,
    ) -> np.ndarray:
        # Rebuild the Jacobian at each iterate so the linearization stays
        # consistent with the current nonlinear state.
        return build_dense_fd_jacobian(
            lambda candidate: assembly_for(candidate).solver_residual,
            head_m,
            residual_m3_s,
            rel_step=float(fd_rel_step),
        )

    def _solve_dense_linear_system(
        jacobian: np.ndarray,
        residual_m3_s: np.ndarray,
        _residual_norm_inf: float,
        _initial_residual_norm_inf: float,
    ) -> np.ndarray:
        try:
            return np.linalg.solve(jacobian, -residual_m3_s)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError("Dense Newton Jacobian solve failed.") from exc

    return _newton_loop_template(
        assembly_for=assembly_for,
        head_initial_guess_m=head_initial_guess_m,
        max_iterations=max_iterations,
        tol_residual_inf=tol_residual_inf,
        min_damping=min_damping,
        backend_name=backend_name,
        newton_label="dense",
        build_jacobian=_build_dense_jacobian,
        solve_linear_system=_solve_dense_linear_system,
    )


__all__ = [
    "solve_steady_problem",
    "solve_transient_step",
]
