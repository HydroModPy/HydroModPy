"""Runtime-backend selection for the Boussinesq solver.

This module keeps backend choice explicit and lightweight. The goal is that the
driver code in :mod:`hydromodpy.solver.boussinesq.boussinesq` can ask for one
named backend without knowing how that backend is implemented internally.

Besides the callables themselves, each backend also exposes descriptive
metadata. That metadata is written to the runtime summary so validation outputs
remain interpretable after the solve has finished.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)

RuntimeBackendName = Literal["local", "scipy", "scipy_sparse"]
LinearSystemLayout = Literal["dense", "sparse", "matrix_free"]


@dataclass(frozen=True)
class BoussinesqRuntimeBackend:
    """Normalized descriptor for one nonlinear runtime backend.

    The two solve callables are the only mandatory execution entry points.
    The extra string fields are not cosmetic: they document how the backend
    reached its answer and are exported in runtime summaries for diagnostics.
    """

    name: RuntimeBackendName
    solve_transient_step: Callable[[TransientStepInputs], RuntimeSolveResult]
    solve_steady_problem: Callable[[SteadySolveInputs], RuntimeSolveResult]
    nonlinear_solver_kind: str
    linear_system_layout: LinearSystemLayout
    convergence_policy: str
    iteration_counter_label: str


def resolve_runtime_backend(name: str | None) -> BoussinesqRuntimeBackend:
    """Return the backend descriptor matching one user-facing backend name.

    Parameters
    ----------
    name:
        Free-form backend token coming from configuration or the flow object.
        The value is normalized to lowercase and defaults to ``"local"``.

    Returns
    -------
    BoussinesqRuntimeBackend
        One descriptor bundling the solve callables and a short explanation of
        the nonlinear strategy used by that backend.
    """
    normalized = str(name or "local").strip().lower() or "local"
    if normalized == "local":
        from hydromodpy.solver.boussinesq.local_runtime import (
            solve_steady_problem,
            solve_transient_step,
        )

        return BoussinesqRuntimeBackend(
            name="local",
            solve_transient_step=solve_transient_step,
            solve_steady_problem=solve_steady_problem,
            nonlinear_solver_kind="newton_line_search_dense_fd",
            linear_system_layout="dense",
            convergence_policy="residual_inf <= tol_residual_inf",
            iteration_counter_label="newton_iterations",
        )
    if normalized == "scipy":
        from hydromodpy.solver.boussinesq.scipy_runtime import (
            solve_steady_problem,
            solve_transient_step,
        )

        return BoussinesqRuntimeBackend(
            name="scipy",
            solve_transient_step=solve_transient_step,
            solve_steady_problem=solve_steady_problem,
            nonlinear_solver_kind="scipy_root_hybr_dense_fd",
            linear_system_layout="dense",
            convergence_policy="state_update_inf <= tol_state_update_inf and residual_inf <= tol_residual_inf",
            iteration_counter_label="function_evaluations",
        )
    if normalized == "scipy_sparse":
        from hydromodpy.solver.boussinesq.scipy_sparse_runtime import (
            solve_steady_problem,
            solve_transient_step,
        )

        return BoussinesqRuntimeBackend(
            name="scipy_sparse",
            solve_transient_step=solve_transient_step,
            solve_steady_problem=solve_steady_problem,
            nonlinear_solver_kind="scipy_sparse_newton_line_search_semianalytic_base_sat_fd_colored",
            linear_system_layout="sparse",
            convergence_policy="residual_inf <= tol_residual_inf",
            iteration_counter_label="newton_iterations",
        )
    raise ValueError(
        "Unsupported Boussinesq runtime backend. Expected one of: "
        "local, scipy, scipy_sparse."
    )


__all__ = [
    "BoussinesqRuntimeBackend",
    "LinearSystemLayout",
    "RuntimeBackendName",
    "resolve_runtime_backend",
]
