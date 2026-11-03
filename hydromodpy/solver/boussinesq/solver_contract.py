"""Process-to-runtime contract helpers for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.physics.flow.boundary_condition_registry import (
    boundary_condition_bundle_from_flow,
    boundary_definition,
)
from hydromodpy.physics.flow.flow_runtime_config import DEFAULT_PARTITION_RELEASE_DEPTH_M
from hydromodpy.physics.flow.regime import normalize_flow_regime
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

if TYPE_CHECKING:
    from hydromodpy.spatial.domain.layers_config import VerticalGridConfig

_SUPPORTED_SINK_SOURCE_IDS = frozenset({"recharge", "wells"})

AUTO_RUNTIME_BACKEND = "auto"
# The dense engines build an n x n Jacobian: memory and time grow as n^2 and n^3.
DENSE_ENGINE_MAX_CELLS = 400


@dataclass(frozen=True)
class BoussinesqSolverContract:
    """Explicit mapping from one `Flow` configuration to one solve path."""

    flow_regime: str
    runtime_backend_requested: str
    surface_interaction_model_requested: str
    surface_interaction_model_resolved: str
    runtime_backend: ResolvedBoussinesqRuntimeBackend


def runtime_backend_name(flow: object) -> str:
    """Return the requested runtime backend token, ``"auto"`` when unset."""
    raw = getattr(flow, "runtime_backend", None)
    return str(raw or AUTO_RUNTIME_BACKEND).strip().lower() or AUTO_RUNTIME_BACKEND


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


def resolve_flow_regime(flow: object) -> str:
    """Return the normalized flow regime expected by the Boussinesq driver."""
    flow_regime = getattr(flow, "flow_regime", None)
    if flow_regime is None:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
    return normalize_flow_regime(flow_regime)


def resolve_surface_interaction_model(flow: object, *, n_cells: int | None = None) -> str:
    """Return the selected groundwater/surface interaction closure."""
    return resolve_surface_interaction_model_token(
        runtime_backend_name=resolve_runtime_backend_name(
            runtime_backend_name(flow),
            n_cells=n_cells,
        ),
        surface_interaction_model=getattr(
            flow,
            "surface_interaction_model",
            "auto",
        ),
    )


def resolve_solver_contract(
    flow: object,
    *,
    n_cells: int | None = None,
) -> BoussinesqSolverContract:
    """Return the explicit solver contract derived from the current `Flow`.

    ``n_cells`` is the size of the solver mesh. It resolves ``"auto"``.
    """
    runtime_backend_requested = runtime_backend_name(flow)
    runtime_backend_resolved = resolve_runtime_backend_name(
        runtime_backend_requested,
        n_cells=n_cells,
    )
    surface_requested = (
        str(getattr(flow, "surface_interaction_model", "auto") or "auto").strip().lower() or "auto"
    )
    surface_resolved = resolve_surface_interaction_model_token(
        runtime_backend_name=runtime_backend_resolved,
        surface_interaction_model=surface_requested,
    )
    runtime_backend = resolve_runtime_backend(
        runtime_backend_resolved,
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
    n_cells: int | None = None,
) -> NonlinearRuntimeOptions:
    """Build backend-neutral nonlinear options for the selected runtime."""
    runtime_backend_resolved = resolve_runtime_backend_name(
        runtime_backend_name(flow),
        n_cells=n_cells,
    )
    max_iterations = 20
    if runtime_backend_resolved == "scipy_sparse":
        # Where the water table reaches the ground over a wide area, Newton slows to
        # a linear rate near the kink of the release: 39 iterations on an island
        # under 7 mm/day, residual 1e-8 at the 30th and falling 20 % per iteration.
        max_iterations = 60
    runtime_max_iterations = getattr(flow, "runtime_max_iterations", None)
    if runtime_max_iterations is not None:
        max_iterations = int(runtime_max_iterations)
    tol_residual_inf = float(getattr(flow, "runtime_tol_residual_inf", 1.0e-9) or 1.0e-9)
    tol_state_update_inf = float(getattr(flow, "runtime_tol_state_update_inf", 1.0e-9) or 1.0e-9)
    vi_substeps_per_period = int(getattr(flow, "vi_substeps_per_period", 1) or 1)
    vi_substep_on_failure = bool(getattr(flow, "vi_substep_on_failure", False))
    vi_max_adaptive_substeps = int(
        getattr(flow, "vi_max_adaptive_substeps", vi_substeps_per_period) or vi_substeps_per_period
    )
    ts_vi_steps_per_period = int(getattr(flow, "ts_vi_steps_per_period", 4) or 4)
    ts_vi_adapt = bool(getattr(flow, "ts_vi_adapt", False))
    ts_vi_dt_min_fraction = float(
        getattr(flow, "ts_vi_dt_min_fraction", 1.0 / 64.0) or (1.0 / 64.0)
    )
    ts_vi_dt_max_fraction = float(getattr(flow, "ts_vi_dt_max_fraction", 1.0 / 4.0) or (1.0 / 4.0))
    ts_vi_type = str(getattr(flow, "ts_vi_type", "beuler") or "beuler")
    ts_vi_snes_type = str(getattr(flow, "ts_vi_snes_type", "vinewtonrsls") or "vinewtonrsls")
    release_depth_m = float(
        getattr(flow, "partition_release_depth_m", DEFAULT_PARTITION_RELEASE_DEPTH_M)
    )
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


def assert_supported_runtime_subset(flow: object) -> None:
    """Fail fast when the requested problem exceeds the implemented slice."""
    boundary_bundle = boundary_condition_bundle_from_flow(flow)
    active_sinks_sources = tuple(getattr(flow, "active_sinks_sources", ()) or ())
    unsupported_bc = sorted(
        set(boundary_bundle.unknown_active_ids())
        | set(boundary_bundle.unsupported_active_ids("boussinesq"))
    )
    unsupported_sinks_sources = sorted(
        str(item) for item in active_sinks_sources if str(item) not in _SUPPORTED_SINK_SOURCE_IDS
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
        raise IncompatibleCapabilitiesError(
            "The boussinesq backend does not support advanced-package boundaries "
            "(LAK lake/reservoir); they require the modflow6 backend. Offending "
            "boundaries: " + ",".join(advanced_bc) + "."
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


def layering_refusal(
    layers: VerticalGridConfig, *, written_in: str = "[domain.layers]"
) -> str | None:
    """Return why Boussinesq refuses ``layers``, or None when they build one layer.

    Boussinesq solves one layer over the whole aquifer column and never reads
    ``[domain.layers]``. More layers, or one base per layer, would be ignored.
    ``written_in`` names where the layering is written.
    """
    if layers.genmtd_lay == "surfaces":
        asked = "gives each layer its own base (genmtd_lay = 'surfaces')"
    elif layers.layer_count > 1:
        asked = f"builds {layers.layer_count} layers (genmtd_lay = {layers.genmtd_lay!r})"
    else:
        return None
    return (
        "solver.backend = 'boussinesq' solves one layer over the whole aquifer, and "
        f"{written_in} {asked}, which boussinesq would ignore. Remove {written_in}, "
        "or run the flow with 'modflow6' or 'modflow_nwt'."
    )


__all__ = [
    "AUTO_RUNTIME_BACKEND",
    "DENSE_ENGINE_MAX_CELLS",
    "BoussinesqSolverContract",
    "assert_supported_runtime_subset",
    "build_runtime_options",
    "layering_refusal",
    "resolve_flow_regime",
    "resolve_runtime_backend_name",
    "resolve_solver_contract",
    "resolve_surface_interaction_model",
    "runtime_backend_name",
]
