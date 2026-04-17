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
from hydromodpy.solver.boussinesq.runtimes.head_only_common import (
    build_steady_assembly_callback,
    build_transient_assembly_callback,
)
from hydromodpy.solver.boussinesq.jacobian.fd import build_dense_fd_jacobian
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtimes.newton_common import (
    _newton_loop_template,
)
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


def solve_backward_euler_step(
    mesh: BoussinesqMesh,
    *,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    head_initial_guess_m: np.ndarray | None = None,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
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
    This convenience wrapper now follows the same canonical contract as the
    main runtime path: Dirichlet data is prescribed on boundary cells.
    """
    return solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray(head_prev_m, dtype=float),
            dt_seconds=float(dt_seconds),
            head_initial_guess_m=head_initial_guess_m,
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
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
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
    max_iterations: int = 20,
    tol_residual_inf: float = 1.0e-9,
    fd_rel_step: float = 1.0e-7,
    min_damping: float = 1.0e-4,
) -> RuntimeSolveResult:
    """Compatibility wrapper around :func:`solve_steady_problem`.

    This convenience wrapper now follows the same canonical contract as the
    main runtime path: Dirichlet data is prescribed on boundary cells.
    """
    return solve_steady_problem(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray(head_initial_guess_m, dtype=float),
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
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
            lambda candidate: assembly_for(candidate).residual_m3_s,
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

LocalStepSolveResult = RuntimeSolveResult

__all__ = [
    "LocalStepSolveResult",
    "solve_backward_euler_step",
    "solve_steady_problem",
    "solve_steady_state",
    "solve_transient_step",
]

