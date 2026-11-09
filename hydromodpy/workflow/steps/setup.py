"""Setup step - structural bootstrap, geographic, spatial supports, process objects."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.catchment.algorithms.derived_features import coerce_geographic_derived_features
from hydromodpy.catchment.preprocess.catchment_delineation import CatchmentDelineation
from hydromodpy.catchment.preprocess.geographic_cache import geographic_artifact_paths
from hydromodpy.catchment.synthetic.catchment import build_synthetic_geographic
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.rng import RngManager
from hydromodpy.core.state.scratch import preprocessing_dir
from hydromodpy.core.workspace import WorkspaceLayout
from hydromodpy.model.domain.build import (
    build_domain,
    read_layer_base_sources,
    read_substratum_source,
    rebuild_domain,
)
from hydromodpy.model.domain.spatial_support import (
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
    build_phase_supports,
    validate_domain_support_contract,
)
from hydromodpy.model.domain.structure_binders import apply_catchment_zones_to_domain
from hydromodpy.results.storage.attempt import scratch_dir_for_attempt
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.data import ensure_flow

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Geographic runtime
# ---------------------------------------------------------------------------


def build_geographic_runtime(
    cfg: object,
    workspace: object,
    *,
    dem_path: Path | None = None,
    reuse_existing_outputs: bool | None = None,
    network_map_path: Path | None = None,
) -> object:
    """Build the geographic runtime selected by the validated TOML config.

    The DEM arrives resolved through ``dem_path``, read from the
    ``[[data.dem.sources]]`` sources before the step runs.
    """
    geographic_cfg = cfg.geographic
    uses_synthetic = getattr(geographic_cfg, "uses_synthetic_geographic", None)
    if callable(uses_synthetic) and uses_synthetic():
        return build_synthetic_geographic(
            config=geographic_cfg.synthetic,
            output_dir=preprocessing_dir(Path(workspace.project_root)) / "geographic",
            workspace=workspace,
        )
    return CatchmentDelineation(
        geographic_cfg,
        workspace,
        dem_path=dem_path,
        reuse_existing_outputs=reuse_existing_outputs,
        network_map_path=network_map_path,
    )


def resolve_geographic_inputs(cfg: object, run_state: WorkflowContext) -> Path | None:
    """Resolve the ``[data]`` files the geographic step reads without mutating the config.

    A synthetic geographic reads no ``[data]`` file, so it resolves nothing.
    Otherwise every file and url source of ``[data]`` is resolved under the
    bounds of the call, before the run is named. The DEM resolution returns a :class:`FileRecord` without writing the
    configuration and ``None`` when the config declares no DEM source; the
    catchment reads its raster through the ``dem_path`` the caller passes on.
    A runner that resolved the inputs when it claimed the run has put them on the
    context (``run_state.inputs``), and they are read from there.
    """
    import hydromodpy.data.variables.crossings.resolver as crossings_resolver
    import hydromodpy.data.variables.hydrography.resolver as hydrography_resolver
    from hydromodpy.data.loading.inputs import resolve_inputs

    paths = getattr(run_state.setup.workspace, "paths", None)
    data_path = getattr(paths, "data_path", None)
    uses_synthetic = getattr(cfg.geographic, "uses_synthetic_geographic", None)
    if callable(uses_synthetic) and uses_synthetic():
        run_state.setup.dem_record = None
        return None
    # A runner has resolved every declared file and url source already, under the
    # bounds of the call. Without one, they are resolved here, before the run is named.
    resolved = run_state.inputs
    if resolved is None:
        resolved = resolve_inputs(cfg, bounds=run_state.bounds, data_dir=data_path)
    dem_record = resolved.dem
    run_state.setup.dem_record = dem_record
    crossings_resolver.fill_crossings_path(
        cfg,
        config_path=run_state.config_path,
        data_path=data_path,
        dem_path=None if dem_record is None else Path(dem_record.path),
    )
    return hydrography_resolver.resolve_network_map_path(cfg, config_path=run_state.config_path)


def step_spatial_supports(
    ctx: WorkflowContext,
    *,
    phase: str,
    requested_domain_supports: dict[str, object] | None = None,
    registry: object | None = None,
) -> None:
    """Materialize declared spatial supports for the given build *phase*."""
    if not requested_domain_supports:
        return
    setup_state = ctx.setup
    build_phase_supports(
        setup_state.domain,
        requested_domain_supports,
        registry=build_default_spatial_support_provider_registry()
        if registry is None
        else registry,
        phase=phase,
        context=SupportBuildContext(
            cfg=ctx.cfg,
            raw_toml=ctx.raw_toml,
            workspace=setup_state.workspace,
            geographic=setup_state.geographic,
            domain_geographic=setup_state.domain_geographic,
            domain=setup_state.domain,
            flow=setup_state.flow,
            loaded_data=ctx.loaded_data,
            time_grid=setup_state.time_grid,
            geographic_features=setup_state.geographic_features,
        ),
    )


# ---------------------------------------------------------------------------
# Setup: workspace, geographic, domain, process objects
# ---------------------------------------------------------------------------


def step_setup(
    ctx: WorkflowContext,
    *,
    requested_spatial_support_ids: tuple[str, ...] = (),
    requested_domain_supports: dict[str, object] | None = None,
    reuse_existing_outputs: bool | None = None,
    run_id: str | None = None,
) -> None:
    """Populate ``ctx.setup`` with workspace, geographic, domain, flow, transport.

    This builds the stable "session context" of the simulation, once, even
    when the simulation plan later contains several solver runs: two flow
    solvers still reuse the same domain geometry and the same declared flow
    configuration.
    """
    cfg = ctx.cfg
    setup_state = ctx.setup

    setup_state.workspace = WorkspaceLayout(config=cfg.workspace)
    if ctx.run_dir is not None:
        setup_state.workspace.solver_scratch_folder = scratch_dir_for_attempt(
            setup_state.workspace.project_root, ctx.run_dir, ctx.attempt
        )
    network_map_path = resolve_geographic_inputs(cfg, ctx)
    dem_record = getattr(setup_state, "dem_record", None)
    dem_path = Path(dem_record.path) if dem_record is not None else None
    setup_state.geographic = build_geographic_runtime(
        cfg,
        setup_state.workspace,
        dem_path=dem_path,
        reuse_existing_outputs=reuse_existing_outputs,
        network_map_path=network_map_path,
    )
    setup_state.geographic_features = coerce_geographic_derived_features(
        geographic=setup_state.geographic,
    )
    if setup_state.geographic_features is None:
        raise ConfigError(
            "Could not resolve geographic derived features from the runtime geographic object."
        )
    setup_state.domain_geographic = setup_state.geographic_features.to_domain_geographic_context()

    setup_state.domain = build_domain(
        cfg.domain,
        surface_topo=setup_state.geographic_features.surface_topo,
        zone_ids=requested_spatial_support_ids,
        substratum_source=read_substratum_source(
            cfg.domain.depth_model, getattr(cfg, "data", None)
        ),
        layer_base_sources=read_layer_base_sources(cfg.domain.layers, getattr(cfg, "data", None)),
    )
    setup_state.domain_config_source = cfg.domain
    apply_catchment_zones_to_domain(
        domain=setup_state.domain,
        geographic=setup_state.domain_geographic,
    )

    # Internal run_id (journal/scratch key): the name the caller gave this run
    # > explicit config name > derive from TOML filename > "default". A caller
    # that already named its run has decided; deriving a name again here would
    # rename it halfway through, and the catalog would register it under a name
    # the journal does not carry.
    if run_id:
        setup_state.run_id = run_id
    elif cfg.simulation.name:
        setup_state.run_id = cfg.simulation.name
    else:
        toml_path = ctx.config_path
        setup_state.run_id = re.sub(r"^run_", "", Path(toml_path).stem) if toml_path else "default"

    rng_seed = getattr(cfg.simulation, "rng_seed", None)
    ctx.execution.rng = RngManager(master_seed=int(rng_seed)) if rng_seed is not None else None

    # Eagerly create Flow so data binders can reference it. Transport has no
    # model object to materialize: its adapter reads the configuration itself.
    ensure_flow(ctx)
    validate_domain_support_contract(setup_state.flow, requested_domain_supports or {})


def rebuild_domain_if_stale(run_state: WorkflowContext) -> bool:
    """Rebuild ``setup.domain`` when another configuration built it.

    A Project builds its model phase once and then drives several runs through
    it. Each run resolves the configuration it is defined by, so a sweep point,
    or a plain run following an overridden one, can arrive with a ``domain``
    section the live geometry was not built from. Nothing downstream compares
    the two: the run would use the previous run's geometry while archiving its
    own configuration beside it.

    Only the domain is rebuilt. The geographic tree and the loaded forcings it
    stands on belong to the project, not to the run, and re-deriving them would
    mean delineating the catchment again at every sweep point.

    Returns True when a rebuild happened.
    """
    from hydromodpy.model.domain.structure_binders import apply_geology_to_domain

    setup_state = run_state.setup
    if setup_state.domain is None:
        return False
    if setup_state.domain_config_source is run_state.cfg.domain:
        return False
    if setup_state.geographic_features is None:
        raise ConfigError(
            "The domain was built from another configuration and cannot be rebuilt: "
            "the geographic runtime it stands on is missing from the context."
        )

    # The rebuilt domain is armed from the zone ids the live domain ended up
    # with, binder ids included, so it can receive the catchment and geology
    # zones: ``step_setup`` arms a copy, so the declared section never carries
    # them. The raster is read again from the run's own configuration, which is
    # what the rebuilt geometry has to describe. The spatial supports the
    # project materialized are lateral zonations; a different aquifer thickness
    # does not invalidate them, and nothing runs ``step_spatial_supports`` again
    # for a repeat run on a live Project. Dropping them here would leave the
    # solver reading no field while ``validate_domain_support_contract``, which
    # reads the config, still passes. The binder zones are written again below.
    domain_cfg = run_state.cfg.domain
    data_cfg = getattr(run_state.cfg, "data", None)
    domain = rebuild_domain(
        setup_state.domain,
        domain_cfg,
        surface_topo=setup_state.geographic_features.surface_topo,
        substratum_source=read_substratum_source(domain_cfg.depth_model, data_cfg),
        layer_base_sources=read_layer_base_sources(domain_cfg.layers, data_cfg),
        keep_binder_zones=False,
    )
    apply_catchment_zones_to_domain(domain=domain, geographic=setup_state.domain_geographic)
    if run_state.loaded_data.geology is not None:
        apply_geology_to_domain(domain=domain, geology=run_state.loaded_data.geology)
    setup_state.domain = domain
    setup_state.domain_config_source = domain_cfg
    return True


def rebuild_substratum_if_depth_model_moved(run_state: WorkflowContext) -> bool:
    """Rebuild the domain when the run's depth model is not the one it was built on.

    A calibration trial writes the thickness of a ``constant_thickness`` model,
    or the elevation of a ``flat_substratum`` one, into its own copy of the
    configuration. The domain it forks from was built once by the shared prefix
    and is the same object for every trial. Without this rebuild each trial
    solves the geometry of the prefix and reports a thickness it never used.

    Only the vertical extent follows the depth model. The top and the lateral
    zones are carried over as they are, so nothing here reads a shapefile or
    delineates a catchment again, and concurrent trials stay independent.

    Returns True when a rebuild happened.
    """
    setup_state = run_state.setup
    domain = setup_state.domain
    if domain is None:
        return False
    declared = run_state.cfg.domain.depth_model
    if domain.config.depth_model == declared:
        return False
    data_cfg = getattr(run_state.cfg, "data", None)
    setup_state.domain = rebuild_domain(
        domain,
        domain.config.model_copy(update={"depth_model": declared.model_copy(deep=True)}),
        surface_topo=domain.surface_topo,
        substratum_source=read_substratum_source(declared, data_cfg),
        layer_base_sources=read_layer_base_sources(domain.config.layers, data_cfg),
    )
    return True


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


class BuildGeographicStep:
    """Build geographic runtime, domain, and setup-phase spatial supports.

    Composed of two substeps invoked through ``run``: :func:`step_setup`
    (workspace + geographic + domain + flow + transport, then the support
    contract check) and :func:`step_spatial_supports` for the setup phase. The
    free-standing helpers stay reusable from notebooks and other launchers.
    """

    name = "build_geographic"
    reads: ClassVar[tuple[str, ...]] = (
        "ctx",
        "requested_domain_supports",
        "requested_spatial_support_ids",
        "run_name",
        "spatial_support_registry",
    )
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ("geographic", "data.dem")

    def depends_on(self) -> tuple[str, ...]:
        return ("resolve",)

    def run(self, state: PipelineState) -> PipelineState:
        return self._build(state, reuse_existing_outputs=None)

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return the geographic tree this step wrote, as the runtime names it."""
        ctx = state_out.get("ctx")
        if ctx is None:
            return ()
        return tuple(
            str(path) for path in geographic_artifact_paths(getattr(ctx.setup, "geographic", None))
        )

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Rebuild the geographic runtime by reading the tree it left on disk.

        The read is forced whatever ``[geographic] reuse_existing_outputs``
        says: that flag decides what a fresh run does with a tree another run
        left, and a resume re-delineating its own products is a defect. A tree
        that is incomplete, or whose description does not match the config,
        still falls back to a full build - which is what the step would have
        done anyway - and says so.
        """
        return self._build(prior_state, reuse_existing_outputs=True)

    def _build(
        self,
        state: PipelineState,
        *,
        reuse_existing_outputs: bool | None,
    ) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildGeographicStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        step_setup(
            ctx,
            requested_spatial_support_ids=state.get("requested_spatial_support_ids", ()),
            requested_domain_supports=requested_supports,
            reuse_existing_outputs=reuse_existing_outputs,
            run_id=state.get("run_name"),
        )
        step_spatial_supports(
            ctx,
            phase="setup",
            requested_domain_supports=requested_supports,
            registry=state.get("spatial_support_registry"),
        )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already carries the setup products."""
        ctx = state.get("ctx")
        if ctx is None:
            return False
        setup = ctx.setup
        return (
            setup.workspace is not None
            and setup.geographic is not None
            and setup.geographic_features is not None
            and setup.domain is not None
        )


class SetupProcessStep:
    """Instantiate flow / transport process objects bound to the domain."""

    name = "setup_process"
    reads: ClassVar[tuple[str, ...]] = ("ctx",)
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = (
        "domain.depth_model",
        "flow.ic",
        "simulation",
    )

    def depends_on(self) -> tuple[str, ...]:
        return ("build_mesh",)

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("SetupProcessStep requires 'ctx' in state.data")

        if getattr(ctx.setup, "domain", None) is not None:
            # This step owns domain.depth_model, so a trial that moves it starts
            # here and must find the geometry it asked for.
            rebuild_substratum_if_depth_model_moved(ctx)
            if getattr(ctx.cfg, "flow", None) is not None:
                ensure_flow(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Re-run setup_process: trivial wrapper, idempotent."""
        return self.run(prior_state)
