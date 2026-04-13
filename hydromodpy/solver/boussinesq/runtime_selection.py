"""Runtime-backend selection for the Boussinesq solver.

This module now resolves two orthogonal choices:

- the physical method, i.e. formulation + surface closure + discretization;
- the execution engine, i.e. the nonlinear solver and linear-algebra backend.

The public entry point remains intentionally lightweight so the driver code in
:mod:`hydromodpy.solver.boussinesq.boussinesq` can still ask for one named
backend without knowing how that backend is implemented internally.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Literal

from hydromodpy.solver.boussinesq.engines import (
    BoussinesqEngineSpec,
    resolve_engine_spec,
)
from hydromodpy.solver.boussinesq.methods import (
    BoussinesqMethodSpec,
    resolve_method_spec,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)

RuntimeBackendName = Literal["local", "scipy", "scipy_sparse", "petsc"]
LinearSystemLayout = Literal["dense", "sparse", "matrix_free"]
SurfaceInteractionModel = Literal["auto", "regularized_partition", "complementarity"]


@dataclass(frozen=True)
class BoussinesqRuntimeBackend:
    """Normalized descriptor for one nonlinear runtime backend.

    The two solve callables are the only mandatory execution entry points.
    The extra string fields are not cosmetic: they document how the backend
    reached its answer and are exported in runtime summaries for diagnostics.
    """

    name: RuntimeBackendName
    engine_id: str
    method: BoussinesqMethodSpec
    solve_transient_step: Callable[[TransientStepInputs], RuntimeSolveResult]
    solve_steady_problem: Callable[[SteadySolveInputs], RuntimeSolveResult]
    nonlinear_solver_kind: str
    linear_system_layout: LinearSystemLayout
    jacobian_strategy: str
    linear_solver_kind: str
    convergence_policy: str
    iteration_counter_label: str


def resolve_runtime_backend(
    name: str | None,
    *,
    surface_interaction_model: SurfaceInteractionModel | str = "auto",
) -> BoussinesqRuntimeBackend:
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
    method = resolve_method_spec(
        runtime_backend_name=normalized,
        surface_interaction_model=surface_interaction_model,
    )
    engine = resolve_engine_spec(
        runtime_backend_name=normalized,
        method_id=method.id,
    )
    solve_steady_problem, solve_transient_step = _load_engine_solvers(engine)
    return BoussinesqRuntimeBackend(
        name=engine.name,  # type: ignore[arg-type]
        engine_id=engine.id,
        method=method,
        solve_transient_step=solve_transient_step,
        solve_steady_problem=solve_steady_problem,
        nonlinear_solver_kind=engine.nonlinear_solver_kind,
        linear_system_layout=engine.linear_system_layout,  # type: ignore[arg-type]
        jacobian_strategy=engine.jacobian_strategy,
        linear_solver_kind=engine.linear_solver_kind,
        convergence_policy=engine.convergence_policy,
        iteration_counter_label=engine.iteration_counter_label,
    )


def _load_engine_solvers(
    engine: BoussinesqEngineSpec,
) -> tuple[
    Callable[[SteadySolveInputs], RuntimeSolveResult],
    Callable[[TransientStepInputs], RuntimeSolveResult],
]:
    """Import the solve callables exposed by one runtime engine module."""

    module = import_module(engine.module_name)
    return (
        getattr(module, "solve_steady_problem"),
        getattr(module, "solve_transient_step"),
    )


__all__ = [
    "BoussinesqRuntimeBackend",
    "LinearSystemLayout",
    "RuntimeBackendName",
    "SurfaceInteractionModel",
    "resolve_runtime_backend",
]
