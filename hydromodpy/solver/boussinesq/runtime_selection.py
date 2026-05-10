"""Runtime-backend selection for the Boussinesq solver.

This module now resolves two orthogonal choices:

- the physical method, i.e. formulation + surface closure + discretization;
- the execution engine, i.e. the nonlinear solver and linear-algebra backend.

The public entry point remains intentionally lightweight so the driver code in
:mod:`hydromodpy.solver.boussinesq.boussinesq` can still ask for one named
backend without knowing how that backend is implemented internally.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol, cast, runtime_checkable

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
SurfaceInteractionModel = Literal[
    "auto",
    "regularized_partition",
    "complementarity",
    "vi_obstacle",
    "ts_vi_obstacle",
]


@runtime_checkable
class BoussinesqRuntimeBackend(Protocol):
    """Minimal execution contract implemented by runtime modules."""

    def solve_transient_step(
        self,
        inputs: TransientStepInputs,
    ) -> RuntimeSolveResult: ...

    def solve_steady_problem(
        self,
        inputs: SteadySolveInputs,
    ) -> RuntimeSolveResult: ...


@dataclass(frozen=True)
class ResolvedBoussinesqRuntimeBackend:
    """Normalized descriptor for one nonlinear runtime backend.

    The two solve callables are the only mandatory execution entry points.
    The extra string fields are not cosmetic: they document how the backend
    reached its answer and are exported in runtime summaries for diagnostics.
    """

    name: RuntimeBackendName
    engine_id: str
    method: BoussinesqMethodSpec
    backend: BoussinesqRuntimeBackend
    nonlinear_solver_kind: str
    linear_system_layout: LinearSystemLayout
    jacobian_strategy: str
    linear_solver_kind: str
    convergence_policy: str
    iteration_counter_label: str

    def solve_transient_step(
        self,
        inputs: TransientStepInputs,
    ) -> RuntimeSolveResult:
        """Delegate one transient step to the resolved runtime module."""
        return self.backend.solve_transient_step(inputs)

    def solve_steady_problem(
        self,
        inputs: SteadySolveInputs,
    ) -> RuntimeSolveResult:
        """Delegate one steady solve to the resolved runtime module."""
        return self.backend.solve_steady_problem(inputs)


def resolve_runtime_backend(
    name: str | None,
    *,
    surface_interaction_model: SurfaceInteractionModel | str = "auto",
) -> ResolvedBoussinesqRuntimeBackend:
    """Return the backend descriptor matching one user-facing backend name.

    Parameters
    ----------
    name:
        Free-form backend token coming from configuration or the flow object.
        The value is normalized to lowercase and defaults to ``"local"``.

    Returns
    -------
    ResolvedBoussinesqRuntimeBackend
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
    backend = _load_engine_backend(engine)
    return ResolvedBoussinesqRuntimeBackend(
        name=engine.name,  # type: ignore[arg-type]
        engine_id=engine.id,
        method=method,
        backend=backend,
        nonlinear_solver_kind=engine.nonlinear_solver_kind,
        linear_system_layout=engine.linear_system_layout,  # type: ignore[arg-type]
        jacobian_strategy=engine.jacobian_strategy,
        linear_solver_kind=engine.linear_solver_kind,
        convergence_policy=engine.convergence_policy,
        iteration_counter_label=engine.iteration_counter_label,
    )


def _load_engine_backend(
    engine: BoussinesqEngineSpec,
) -> BoussinesqRuntimeBackend:
    """Import one runtime module and validate the backend execution contract."""

    module = import_module(engine.module_name)
    if not isinstance(module, BoussinesqRuntimeBackend):
        missing = [
            name
            for name in ("solve_steady_problem", "solve_transient_step")
            if not callable(getattr(module, name, None))
        ]
        missing_text = ", ".join(missing) if missing else "required runtime entry points"
        raise TypeError(
            f"{engine.module_name} does not implement the Boussinesq runtime "
            f"backend protocol; missing {missing_text}."
        )
    return cast(BoussinesqRuntimeBackend, module)


__all__ = [
    "BoussinesqRuntimeBackend",
    "ResolvedBoussinesqRuntimeBackend",
    "LinearSystemLayout",
    "RuntimeBackendName",
    "SurfaceInteractionModel",
    "resolve_runtime_backend",
]
