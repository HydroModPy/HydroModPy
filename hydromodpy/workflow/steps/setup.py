"""Setup step - structural bootstrap, geographic, spatial supports, process objects."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.rng import RngManager
from hydromodpy.core.workspace import Workspace
from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from hydromodpy.simulation import ensure_flow, ensure_transport
from hydromodpy.spatial.domain import Domain
from hydromodpy.spatial.domain.spatial_support import SupportBuildContext
from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.core.derived_features import (
    coerce_geographic_derived_features,
)
from hydromodpy.spatial.geographic.structure_binders import apply_catchment_zones_to_domain
from hydromodpy.spatial.geographic.synthetic import build_synthetic_geographic
from hydromodpy.workflow.internals.state import (
    GeographicState,
    MeshedState,
    PipelineState,
    ResolvedState,
    SetupState,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Geographic runtime
# ---------------------------------------------------------------------------


def build_geographic_runtime(cfg: object, workspace: object) -> object:
    """Build the geographic runtime selected by the validated TOML config."""
    geographic_cfg = cfg.geographic
    uses_synthetic = getattr(geographic_cfg, "uses_synthetic_geographic", None)
    if callable(uses_synthetic) and uses_synthetic():
        return build_synthetic_geographic(
            config=geographic_cfg.synthetic,
            output_dir=Path(workspace.project_root) / PREPROCESSING_DIR / "geographic",
            workspace=workspace,
        )
    return CatchmentDelineation(geographic_cfg, workspace)


def resolve_dem_init_path(cfg: object, run_state: WorkflowContext) -> None:
    """Populate ``geographic.dem_init_path`` from ``[[data.dem.sources]]`` when absent.

    Keeps DEM declarations symmetrical with other data managers: a user
    can either set ``geographic.dem_init_path`` directly (shortcut) or
    declare ``[[data.dem.sources]] source = "custom" path = ...`` (same
    pattern as geology, hydrometry, etc.). The geographic pipeline only
    ever sees a resolved path.
    """
    geographic_cfg = cfg.geographic
    uses_synthetic = getattr(geographic_cfg, "uses_synthetic_geographic", None)
    if callable(uses_synthetic) and uses_synthetic():
        return

    existing = getattr(geographic_cfg, "dem_init_path", None)
    if existing is not None:
        return
    if not _cfg_declares_dem_source(cfg):
        return

    from hydromodpy.data.variables.dem.resolver import (
        resolve_dem_path_from_data_sources,
    )

    config_path = run_state.config_path
    if config_path is None:
        raise ConfigError(
            "geographic.dem_init_path is missing and no config path is available "
            "to resolve [[data.dem.sources]]."
        )

    cache_dir = None
    workspace = run_state.setup.workspace
    paths = getattr(workspace, "paths", None) if workspace is not None else None
    data_path = getattr(paths, "data_path", None) if paths is not None else None
    if data_path is not None:
        cache_dir = Path(data_path) / "dem"

    resolved = resolve_dem_path_from_data_sources(
        cfg,
        config_path=Path(config_path),
        cache_dir=cache_dir,
    )
    if resolved is not None:
        geographic_cfg.dem_init_path = resolved
        return
    raise ConfigError(
        "geographic.dem_init_path is missing and [[data.dem.sources]] did not resolve."
    )


def _cfg_declares_dem_source(cfg: object) -> bool:
    data_cfg = getattr(cfg, "data", None)
    dem_cfg = getattr(data_cfg, "dem", None)
    return bool(getattr(dem_cfg, "sources", None))


# ---------------------------------------------------------------------------
# Spatial support helpers
# ---------------------------------------------------------------------------


def collect_requested_support_ids(flow_cfg: object) -> tuple[str, ...]:
    """Return the ordered support ids referenced by heterogeneous flow parameters."""
    raw_param_cfg = getattr(flow_cfg, "param", {})
    if not isinstance(raw_param_cfg, dict):
        return ()

    requested: list[str] = []
    seen: set[str] = set()
    for param_cfg in raw_param_cfg.values():
        if not isinstance(param_cfg, dict):
            continue
        kind = str(param_cfg.get("kind", "")).strip().lower()
        if kind != "heterogeneous":
            continue
        support_id = str(param_cfg.get("field_spatial_id", "")).strip()
        if support_id == "":
            raise ConfigError("Heterogeneous flow parameters require a non-empty field_spatial_id.")
        normalized = support_id.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        requested.append(support_id)
    return tuple(requested)


def support_provider_names(domain_supports: dict[str, object]) -> tuple[str, ...]:
    """Return the ordered provider names declared by resolved support configs."""
    provider_names: list[str] = []
    seen: set[str] = set()
    for support_cfg in domain_supports.values():
        provider_name = str(getattr(support_cfg, "provider", "")).strip().lower()
        if provider_name == "" or provider_name in seen:
            continue
        seen.add(provider_name)
        provider_names.append(provider_name)
    return tuple(provider_names)


def resolve_support_configs(
    domain_cfg: object,
    requested_support_ids: tuple[str, ...],
) -> dict[str, object]:
    """Resolve support configs actually needed by the current flow parameters."""
    if not requested_support_ids:
        return {}

    explicit_supports = getattr(domain_cfg, "supports", {})
    if explicit_supports is None:
        explicit_supports = {}
    if not isinstance(explicit_supports, dict):
        raise TypeError("domain.supports must be a dictionary")

    explicit_by_lower = {
        str(support_id).strip().lower(): support_cfg
        for support_id, support_cfg in explicit_supports.items()
    }

    resolved: dict[str, object] = {}
    for support_id in requested_support_ids:
        support_cfg = explicit_by_lower.get(str(support_id).strip().lower())
        if support_cfg is not None:
            resolved[support_id] = support_cfg
            continue
        raise ConfigError(
            f"Missing domain support declaration for '{support_id}'. "
            "Declare [domain.supports.<id>] with an explicit provider."
        )
    return resolved


def flow_requires_spatial_support(flow: object | None) -> bool:
    """Return True when at least one flow parameter is heterogeneous."""
    if flow is None:
        return False
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return False
    return any(bool(getattr(param, "is_heterogeneous", False)) for param in parameters.values())


def augment_runtime_zone_ids(
    domain_cfg: object,
    requested_spatial_support_ids: tuple[str, ...],
) -> object:
    """Ensure runtime-only zone ids required by launcher bindings are declared."""
    zone_ids = getattr(domain_cfg, "zone_ids", None)
    if zone_ids is None:
        zone_ids = []
        domain_cfg.zone_ids = zone_ids
    if not isinstance(zone_ids, list):
        zone_ids = list(zone_ids)
        domain_cfg.zone_ids = zone_ids

    normalized_zone_ids = {str(item).strip().lower() for item in zone_ids}
    if "catchment" not in normalized_zone_ids:
        zone_ids.append("catchment")
        normalized_zone_ids.add("catchment")

    for support_id in requested_spatial_support_ids:
        normalized_support_id = str(support_id).strip().lower()
        if normalized_support_id in normalized_zone_ids:
            continue
        zone_ids.append(str(support_id).strip())
        normalized_zone_ids.add(normalized_support_id)
    return domain_cfg


def validate_domain_support_contract(
    domain_cfg: object,
    flow: object | None,
    requested_domain_supports: dict[str, object],
) -> None:
    """Fail early when heterogeneous flow parameters reference undeclared supports."""
    _ = domain_cfg
    if not flow_requires_spatial_support(flow):
        return
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        return

    declared_supports = {
        str(support_id).strip().lower()
        for support_id in requested_domain_supports
        if str(support_id).strip()
    }
    missing_supports: list[str] = []
    seen: set[str] = set()
    for param in parameters.values():
        if not bool(getattr(param, "is_heterogeneous", False)):
            continue
        support_id = str(getattr(param, "field_spatial_id", "")).strip()
        if support_id == "":
            raise ConfigError("Heterogeneous flow parameters require a non-empty field_spatial_id.")
        normalized_support_id = support_id.lower()
        if normalized_support_id in declared_supports or normalized_support_id in seen:
            continue
        seen.add(normalized_support_id)
        missing_supports.append(support_id)

    if missing_supports:
        raise ConfigError(
            "Heterogeneous flow parameters require explicit "
            "[domain.supports.<id>] declarations for: " + ", ".join(missing_supports) + "."
        )


def build_domain_spatial_supports(
    cfg: object,
    run_state: WorkflowContext,
    requested_domain_supports: dict[str, object],
    registry: object,
    phase: str,
) -> None:
    """Materialize declared spatial supports for the requested launcher phase."""
    if not requested_domain_supports:
        return

    setup_state = run_state.setup
    context = SupportBuildContext(
        cfg=cfg,
        raw_toml=run_state.raw_toml,
        workspace=setup_state.workspace,
        geographic=setup_state.geographic,
        domain_geographic=setup_state.domain_geographic,
        domain=setup_state.domain,
        flow=setup_state.flow,
        loaded_data=run_state.loaded_data,
        time_grid=setup_state.time_grid,
        geographic_features=setup_state.geographic_features,
    )

    for support_id, support_cfg in requested_domain_supports.items():
        existing_zone = None
        domain_get_zone = getattr(setup_state.domain, "get_zone", None)
        if callable(domain_get_zone):
            existing_zone = domain_get_zone(support_id)
        elif str(support_id).strip().lower() in getattr(setup_state.domain, "zones", {}):
            existing_zone = setup_state.domain.zones[str(support_id).strip().lower()]
        if (
            existing_zone is not None
            and str(getattr(existing_zone, "identifier", "")).strip() == str(support_id).strip()
        ):
            continue
        provider = registry.get(getattr(support_cfg, "provider", ""))
        if str(provider.build_phase).strip().lower() != str(phase).strip().lower():
            continue
        support_field = provider.build(
            support_id=support_id,
            config=support_cfg,
            context=context,
        )
        setup_state.domain.set_zone(support_id, support_field)


# ---------------------------------------------------------------------------
# Main setup orchestration
# ---------------------------------------------------------------------------


def run_setup(
    cfg: object,
    run_state: WorkflowContext,
    *,
    requested_spatial_support_ids: tuple[str, ...] = (),
    requested_domain_supports: dict[str, object] | None = None,
    build_geographic_fn: Callable[..., object] = build_geographic_runtime,
) -> None:
    """Initialise the structural objects shared by all later process runs.

    This function builds the stable "session context" of the simulation:

    - workspace and folders,
    - geographic context and topographic support,
    - domain geometry,
    - process-level context objects (``flow``, ``transport``),
    - generic launcher settings.

    It runs once, even when the simulation plan later contains several
    solver runs. For example, two flow solvers still reuse the same domain
    geometry and the same declared flow configuration.
    """
    if requested_domain_supports is None:
        requested_domain_supports = {}

    setup_state = run_state.setup

    setup_state.workspace = Workspace(config=cfg.workspace)
    resolve_dem_init_path(cfg, run_state)
    setup_state.geographic = build_geographic_fn(cfg, setup_state.workspace)
    setup_state.geographic_features = coerce_geographic_derived_features(
        geographic=setup_state.geographic,
    )
    if setup_state.geographic_features is None:
        raise ConfigError(
            "Could not resolve geographic derived features from the runtime geographic object."
        )
    setup_state.domain_geographic = setup_state.geographic_features.to_domain_geographic_context()
    surface_topo = setup_state.geographic_features.surface_topo

    domain_cfg = cfg.domain
    if hasattr(domain_cfg, "model_copy"):
        domain_cfg = domain_cfg.model_copy(deep=True)
    domain_cfg = augment_runtime_zone_ids(domain_cfg, requested_spatial_support_ids)

    setup_state.domain = Domain(config=domain_cfg, surface_topo=surface_topo)
    apply_catchment_zones_to_domain(
        domain=setup_state.domain,
        geographic=setup_state.domain_geographic,
    )

    # Set run_id: explicit config > derive from TOML filename > "default".
    if cfg.simulation.run_id:
        setup_state.run_id = cfg.simulation.run_id
    else:
        import re

        toml_path = run_state.config_path
        setup_state.run_id = re.sub(r"^run_", "", Path(toml_path).stem) if toml_path else "default"

    rng_seed = getattr(cfg.simulation, "rng_seed", None)
    run_state.execution.rng = (
        RngManager(master_seed=int(rng_seed)) if rng_seed is not None else None
    )

    # Eagerly create Flow/Transport so data binders can reference them.
    ensure_flow(run_state)
    ensure_transport(run_state)
    validate_domain_support_contract(
        domain_cfg=domain_cfg,
        flow=setup_state.flow,
        requested_domain_supports=requested_domain_supports,
    )


# ---------------------------------------------------------------------------
# Step entry point (unified signature for workflow pipelines)
# ---------------------------------------------------------------------------


def step_setup(
    ctx: WorkflowContext,
    *,
    requested_spatial_support_ids: tuple[str, ...] = (),
    requested_domain_supports: dict[str, object] | None = None,
) -> None:
    """Populate ``ctx.setup`` with workspace, geographic, domain, flow, transport."""
    run_setup(
        ctx.cfg,
        ctx,
        requested_spatial_support_ids=requested_spatial_support_ids,
        requested_domain_supports=requested_domain_supports,
    )


# ---------------------------------------------------------------------------
# Spatial supports phase
# ---------------------------------------------------------------------------


def step_spatial_supports(
    ctx: WorkflowContext,
    *,
    phase: str,
    requested_domain_supports: dict[str, object] | None = None,
    registry: object | None = None,
) -> None:
    """Materialize declared spatial supports for the given build *phase*."""
    if requested_domain_supports is None:
        requested_domain_supports = {}
    if not requested_domain_supports:
        return

    if registry is None:
        from hydromodpy.spatial.domain.spatial_support import (
            build_default_spatial_support_provider_registry,
        )

        registry = build_default_spatial_support_provider_registry()

    build_domain_spatial_supports(
        cfg=ctx.cfg,
        run_state=ctx,
        requested_domain_supports=requested_domain_supports,
        registry=registry,
        phase=phase,
    )


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


class BuildGeographicStep:
    """Build geographic runtime, domain, and setup-phase spatial supports."""

    name = "build_geographic"
    tin: ClassVar[type] = ResolvedState
    tout: ClassVar[type] = GeographicState
    config_sections: ClassVar[tuple[str, ...]] = ("geographic", "data.dem")

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildGeographicStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        requested_support_ids = state.get("requested_spatial_support_ids", ())
        registry = state.get("spatial_support_registry")

        step_setup(
            ctx,
            requested_spatial_support_ids=requested_support_ids,
            requested_domain_supports=requested_supports,
        )
        step_spatial_supports(
            ctx,
            phase="setup",
            requested_domain_supports=requested_supports,
            registry=registry,
        )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )


class SetupProcessStep:
    """Instantiate flow / transport process objects bound to the domain."""

    name = "setup_process"
    tin: ClassVar[type] = MeshedState
    tout: ClassVar[type] = SetupState
    config_sections: ClassVar[tuple[str, ...]] = (
        "domain.depth_model",
        "flow.ic",
        "simulation",
    )

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("SetupProcessStep requires 'ctx' in state.data")

        if getattr(ctx.setup, "domain", None) is not None:
            flow_cfg = getattr(ctx.cfg, "flow", None)
            if flow_cfg is not None:
                ensure_flow(ctx)
            transport_cfg = getattr(ctx.cfg, "transport", None)
            if transport_cfg is not None:
                ensure_transport(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )
