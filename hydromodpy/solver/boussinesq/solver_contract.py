"""Process-to-runtime contract helpers for the Boussinesq solver.

The solver reads two objects. The ``Model`` says what is solved, and the options
object, the ``BoussinesqOptions`` of ``[solver.boussinesq]``, says how the nonlinear
solve runs. The MODFLOW solvers read none of those options.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.model.boundaries.boundary_condition_registry import boundary_definition
from hydromodpy.solver.base.registry import backends_honoring
from hydromodpy.solver.boussinesq.catalog import (
    ResolvedBoussinesqRuntimeBackend,
    resolve_runtime_backend,
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
)

if TYPE_CHECKING:
    from hydromodpy.model.model import Model

AUTO_RUNTIME_BACKEND = "auto"
# The dense engines build an n x n Jacobian: memory and time grow as n^2 and n^3.
DENSE_ENGINE_MAX_CELLS = 400


@dataclass(frozen=True)
class BoussinesqSolverContract:
    """Explicit mapping from one ``Model`` and its options to one solve path."""

    flow_regime: str
    runtime_backend_requested: str
    surface_interaction_model_requested: str
    surface_interaction_model_resolved: str
    runtime_backend: ResolvedBoussinesqRuntimeBackend


def runtime_backend_name(runtime: BoussinesqOptions) -> str:
    """Return the requested runtime backend token, ``"auto"`` when unset."""
    return str(runtime.backend or AUTO_RUNTIME_BACKEND).strip().lower() or AUTO_RUNTIME_BACKEND


def resolve_runtime_backend_name(requested: str, *, n_cells: int | None) -> str:
    """Return the engine that runs one requested backend on a mesh of ``n_cells``.

    ``"auto"`` runs the dense ``local`` engine up to ``DENSE_ENGINE_MAX_CELLS``
    cells and the sparse ``scipy_sparse`` engine above. An explicit name is
    returned as is. Without a mesh size, ``"auto"`` resolves to ``local``.
    """
    name = str(requested or AUTO_RUNTIME_BACKEND).strip().lower() or AUTO_RUNTIME_BACKEND
    if name != AUTO_RUNTIME_BACKEND:
        return name
    if n_cells is not None and int(n_cells) > DENSE_ENGINE_MAX_CELLS:
        return "scipy_sparse"
    return "local"


def resolve_flow_regime(model: Model) -> str:
    """Return the flow regime of the model, ``"steady"`` or ``"transient"``."""
    return str(model.time.regime)


def resolve_surface_interaction_model(
    runtime: BoussinesqOptions, *, n_cells: int | None = None
) -> str:
    """Return the selected groundwater/surface interaction closure."""
    return resolve_surface_interaction_model_token(
        runtime_backend_name=resolve_runtime_backend_name(
            runtime_backend_name(runtime),
            n_cells=n_cells,
        ),
        surface_interaction_model=runtime.surface_interaction_model,
    )


def steady_initialization_runtime(runtime: BoussinesqOptions) -> BoussinesqOptions:
    """Return the options of the auxiliary steady solve of a ``steady_state`` start.

    PETSc integrates ``ts_vi_obstacle`` in time, so its steady form is not the
    problem the auxiliary solve has to answer. That solve runs the
    ``regularized_partition`` closure instead, and the transient solve that
    follows brings the head back inside its bounds. Every other option set
    runs unchanged.
    """
    requested = str(runtime.surface_interaction_model or "").strip().lower()
    if runtime_backend_name(runtime) == "petsc" and requested == "ts_vi_obstacle":
        return runtime.model_copy(update={"surface_interaction_model": "regularized_partition"})
    return runtime


def resolve_solver_contract(
    model: Model,
    runtime: BoussinesqOptions,
    *,
    n_cells: int | None = None,
) -> BoussinesqSolverContract:
    """Return the explicit solver contract of one model and its options.

    ``n_cells`` is the size of the solver mesh. It resolves ``"auto"``.
    """
    runtime_backend_requested = runtime_backend_name(runtime)
    runtime_backend_resolved = resolve_runtime_backend_name(
        runtime_backend_requested,
        n_cells=n_cells,
    )
    surface_requested = str(runtime.surface_interaction_model or "auto").strip().lower() or "auto"
    surface_resolved = resolve_surface_interaction_model_token(
        runtime_backend_name=runtime_backend_resolved,
        surface_interaction_model=surface_requested,
    )
    runtime_backend = resolve_runtime_backend(
        runtime_backend_resolved,
        surface_interaction_model=surface_resolved,
    )
    return BoussinesqSolverContract(
        flow_regime=resolve_flow_regime(model),
        runtime_backend_requested=runtime_backend_requested,
        surface_interaction_model_requested=surface_requested,
        surface_interaction_model_resolved=surface_resolved,
        runtime_backend=runtime_backend,
    )


def build_runtime_options(
    runtime: BoussinesqOptions,
    *,
    n_cells: int | None = None,
) -> NonlinearRuntimeOptions:
    """Build backend-neutral nonlinear options for the selected runtime."""
    runtime_backend_resolved = resolve_runtime_backend_name(
        runtime_backend_name(runtime),
        n_cells=n_cells,
    )
    max_iterations = 20
    if runtime_backend_resolved == "scipy_sparse":
        # Where the water table reaches the ground over a wide area, Newton slows to
        # a linear rate near the kink of the release: 39 iterations on an island
        # under 7 mm/day, residual 1e-8 at the 30th and falling 20 % per iteration.
        max_iterations = 60
    if runtime.max_iterations is not None:
        max_iterations = int(runtime.max_iterations)
    tol_residual_inf = float(runtime.tol_residual_inf or 1.0e-9)
    tol_state_update_inf = float(runtime.tol_state_update_inf or 1.0e-9)
    vi_substeps_per_period = int(runtime.vi_substeps_per_period or 1)
    vi_substep_on_failure = bool(runtime.vi_substep_on_failure)
    vi_max_adaptive_substeps = int(runtime.vi_max_adaptive_substeps or vi_substeps_per_period)
    ts_vi_steps_per_period = int(runtime.ts_vi_steps_per_period or 4)
    ts_vi_adapt = bool(runtime.ts_vi_adapt)
    ts_vi_dt_min_fraction = float(runtime.ts_vi_dt_min_fraction or (1.0 / 64.0))
    ts_vi_dt_max_fraction = float(runtime.ts_vi_dt_max_fraction or (1.0 / 4.0))
    ts_vi_type = str(runtime.ts_vi_type or "beuler")
    ts_vi_snes_type = str(runtime.ts_vi_snes_type or "vinewtonrsls")
    release_depth_m = float(runtime.partition_release_depth_m)
    return NonlinearRuntimeOptions(
        regularization_radius=release_depth_m,
        max_iterations=int(max_iterations),
        tol_residual_inf=tol_residual_inf,
        tol_state_update_inf=tol_state_update_inf,
        vi_substeps_per_period=vi_substeps_per_period,
        vi_substep_on_failure=vi_substep_on_failure,
        vi_max_adaptive_substeps=vi_max_adaptive_substeps,
        ts_vi_steps_per_period=ts_vi_steps_per_period,
        ts_vi_adapt=ts_vi_adapt,
        ts_vi_dt_min_fraction=ts_vi_dt_min_fraction,
        ts_vi_dt_max_fraction=ts_vi_dt_max_fraction,
        ts_vi_type=ts_vi_type,
        ts_vi_snes_type=ts_vi_snes_type,
    )


def assert_supported_runtime_subset(model: Model, supports: Set[str]) -> None:
    """Fail fast when the model asks for a boundary or a sink the solver does not build.

    ``supports`` is what the Boussinesq adapter lists. The configuration refuses
    the same traits while the file is read. This check stays for what the build
    adds after the read, such as an ETP injected from loaded data, and for a
    ``Model`` built in Python.
    """
    boundary_bundle = model.boundaries
    unsupported_bc = sorted(
        set(boundary_bundle.unknown_active_ids())
        | set(boundary_bundle.active_ids_outside(frozenset(supports)))
    )
    unsupported_sinks_sources = sorted(
        str(item) for item in model.active_sinks_sources if str(item) not in supports
    )

    # An advanced package (LAK lake/reservoir) is a capability the boussinesq
    # backend does not implement at all -> the typed capability error (HMPY.E407).
    advanced_bc = sorted(
        bc_id
        for bc_id in unsupported_bc
        if (definition := boundary_definition(bc_id)) is not None
        and definition.family == "advanced_package"
    )
    if advanced_bc:
        honoring = backends_honoring("lake")
        raise IncompatibleCapabilitiesError(
            "The boussinesq backend does not support advanced-package boundaries "
            "(LAK lake/reservoir); they require a backend that honors the lake "
            "boundary, and this installation serves: "
            + (", ".join(honoring) or "none")
            + ". Offending boundaries: "
            + ",".join(advanced_bc)
            + "."
        )

    unsupported: list[str] = []
    if unsupported_bc:
        unsupported.append("boundaries " + ",".join(unsupported_bc))
    if unsupported_sinks_sources:
        unsupported.append("sinks and sources " + ",".join(unsupported_sinks_sources))

    if unsupported:
        raise NotImplementedError(
            "The current boussinesq backend slice supports recharge, XY "
            "wells, side Dirichlet boundaries, stream, ocean, "
            "top drainage, and default no-flow on other outer edges. The "
            "following runtime features are not implemented yet: " + "; ".join(unsupported) + "."
        )


__all__ = [
    "AUTO_RUNTIME_BACKEND",
    "DENSE_ENGINE_MAX_CELLS",
    "BoussinesqSolverContract",
    "assert_supported_runtime_subset",
    "build_runtime_options",
    "resolve_flow_regime",
    "resolve_runtime_backend_name",
    "resolve_solver_contract",
    "resolve_surface_interaction_model",
    "runtime_backend_name",
    "steady_initialization_runtime",
]
