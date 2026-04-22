"""Process-to-runtime contract helpers for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.physics.flow.boundary_conditions import SIDE_DIRICHLET_BC_IDS
from hydromodpy.solver.boussinesq.methods import (
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
)
from hydromodpy.solver.boussinesq.runtime_selection import (
    ResolvedBoussinesqRuntimeBackend,
    resolve_runtime_backend,
)

_SUPPORTED_BC_IDS = frozenset(set(SIDE_DIRICHLET_BC_IDS) | {"stream", "ocean", "drainage"})
_SUPPORTED_SINK_SOURCE_IDS = frozenset({"recharge", "wells"})


@dataclass(frozen=True)
class BoussinesqSolverContract:
    """Explicit mapping from one `Flow` configuration to one solve path."""

    flow_regime: str
    runtime_backend_requested: str
    surface_interaction_model_requested: str
    surface_interaction_model_resolved: str
    runtime_backend: ResolvedBoussinesqRuntimeBackend


def runtime_backend_name(flow: object) -> str:
    """Return the selected nonlinear runtime backend name."""
    return str(getattr(flow, "runtime_backend", "local") or "local").strip().lower() or "local"


def resolve_flow_regime(flow: object) -> str:
    """Return the normalized flow regime expected by the Boussinesq driver."""
    flow_regime = getattr(flow, "flow_regime", None)
    if flow_regime is None:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
    flow_regime_text = str(flow_regime).strip().lower()
    if flow_regime_text not in {"steady", "transient"}:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
    return flow_regime_text


def resolve_surface_interaction_model(flow: object) -> str:
    """Return the selected groundwater/surface interaction closure."""
    return resolve_surface_interaction_model_token(
        runtime_backend_name=runtime_backend_name(flow),
        surface_interaction_model=getattr(
            flow,
            "surface_interaction_model",
            "auto",
        ),
    )


def resolve_solver_contract(flow: object) -> BoussinesqSolverContract:
    """Return the explicit solver contract derived from the current `Flow`."""
    runtime_backend_requested = runtime_backend_name(flow)
    surface_requested = (
        str(getattr(flow, "surface_interaction_model", "auto") or "auto").strip().lower() or "auto"
    )
    surface_resolved = resolve_surface_interaction_model_token(
        runtime_backend_name=runtime_backend_requested,
        surface_interaction_model=surface_requested,
    )
    runtime_backend = resolve_runtime_backend(
        runtime_backend_requested,
        surface_interaction_model=surface_resolved,
    )
    return BoussinesqSolverContract(
        flow_regime=resolve_flow_regime(flow),
        runtime_backend_requested=runtime_backend_requested,
        surface_interaction_model_requested=surface_requested,
        surface_interaction_model_resolved=surface_resolved,
        runtime_backend=runtime_backend,
    )


def build_runtime_options(
    flow: object,
    *,
    regularization_radius: float,
) -> NonlinearRuntimeOptions:
    """Build backend-neutral nonlinear options for the selected runtime."""
    runtime_backend_requested = resolve_solver_contract(flow).runtime_backend_requested
    max_iterations = 20
    if runtime_backend_requested == "scipy_sparse":
        # The sparse Newton backend converges reliably on the larger 2-D
        # validation meshes, but it can need a few extra nonlinear
        # iterations beyond the dense prototype defaults.
        max_iterations = 30
    runtime_max_iterations = getattr(flow, "runtime_max_iterations", None)
    if runtime_max_iterations is not None:
        max_iterations = int(runtime_max_iterations)
    tol_residual_inf = float(getattr(flow, "runtime_tol_residual_inf", 1.0e-9) or 1.0e-9)
    tol_state_update_inf = float(getattr(flow, "runtime_tol_state_update_inf", 1.0e-9) or 1.0e-9)
    return NonlinearRuntimeOptions(
        regularization_radius=float(regularization_radius),
        max_iterations=int(max_iterations),
        tol_residual_inf=tol_residual_inf,
        tol_state_update_inf=tol_state_update_inf,
    )


def assert_supported_runtime_subset(flow: object) -> None:
    """Fail fast when the requested problem exceeds the implemented slice."""
    active_bc = tuple(getattr(flow, "active_bc", ()) or ())
    active_sinks_sources = tuple(getattr(flow, "active_sinks_sources", ()) or ())
    unsupported_bc = sorted(str(item) for item in active_bc if str(item) not in _SUPPORTED_BC_IDS)
    unsupported_sinks_sources = sorted(
        str(item) for item in active_sinks_sources if str(item) not in _SUPPORTED_SINK_SOURCE_IDS
    )
    unsupported: list[str] = []
    if unsupported_bc:
        unsupported.append("active_bc=" + ",".join(unsupported_bc))
    if unsupported_sinks_sources:
        unsupported.append("active_sinks_sources=" + ",".join(unsupported_sinks_sources))

    if unsupported:
        raise NotImplementedError(
            "The current boussinesq backend slice supports recharge, XY "
            "wells, side Dirichlet boundaries, stream, ocean, "
            "top drainage, and default no-flow on other outer edges. The "
            "following runtime features are not implemented yet: " + "; ".join(unsupported) + "."
        )


__all__ = [
    "BoussinesqSolverContract",
    "assert_supported_runtime_subset",
    "build_runtime_options",
    "resolve_flow_regime",
    "resolve_solver_contract",
    "resolve_surface_interaction_model",
    "runtime_backend_name",
]
