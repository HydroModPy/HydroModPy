"""Planning step - build a SimulationPlan and align ResultsConfig with the plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.simulation.planning.results_config import ResultsConfig
    from hydromodpy.spatial.domain import Domain

logger = get_logger(__name__)


DEFAULT_FLOW_PROCESS_ID = "flow_main"


def step_build_plan(
    ctx: WorkflowContext,
    *,
    name: str,
    overrides: dict[str, Any] | None = None,
    thickness: float | None = None,
    first_clim: str | None = None,
    solver: str | None = None,
) -> SimulationPlan:
    """Build the SimulationPlan to execute.

    When overrides, thickness or first_clim are provided, synthesize a minimal
    single-flow plan with patched Flow parameters. Otherwise delegate to
    SimulationPlanner using the declared simulation.process list. Sets
    ctx.setup.run_id, ctx.execution.simulation_plan and the process-run map.
    """
    if overrides or thickness is not None or first_clim is not None:
        return _build_plan_with_overrides(
            ctx,
            name=name,
            overrides=overrides or {},
            thickness=thickness,
            first_clim=first_clim,
            solver=solver,
        )
    return _build_plan_from_config(ctx, name=name)


def _build_plan_from_config(ctx: WorkflowContext, *, name: str) -> SimulationPlan:
    from hydromodpy.simulation import SimulationPlanner

    plan = SimulationPlanner().build(ctx.cfg.simulation)
    ctx.setup.run_id = name
    ctx.execution.simulation_plan = plan
    ctx.execution.process_runs_by_id = {r.id: r for r in plan.runs}
    return plan


def _build_plan_with_overrides(
    ctx: WorkflowContext,
    *,
    name: str,
    overrides: dict[str, Any],
    thickness: float | None,
    first_clim: str | None,
    solver: str | None,
) -> SimulationPlan:
    from hydromodpy.physics.flow import Flow
    from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
    from hydromodpy.workflow.steps.data import apply_structural_updates_from_data

    flow = Flow(config=ctx.cfg.flow)
    step_apply_flow_overrides(flow, overrides)

    if first_clim is not None:
        recharge_ss = getattr(flow, "sinks_sources", {})
        if "recharge" in recharge_ss:
            recharge_ss["recharge"].first_clim = first_clim

    domain = ctx.setup.domain
    if thickness is not None:
        domain = step_rebuild_domain(ctx, thickness=thickness)

    ctx.setup.flow = flow
    ctx.setup.run_id = name
    ctx.setup.domain = domain

    # Run the SAME full binder cascade the canonical data step and the trial fork
    # use, so an override / sweep run keeps every forcing (lake meteo and flux,
    # runoff -> SFR, ETP, oceanic) instead of a partial hand-maintained list.
    apply_structural_updates_from_data(ctx)

    solver_name = solver or _default_flow_solver(ctx)
    run_entry = ProcessRun(
        id=ProcessRun.build_id(DEFAULT_FLOW_PROCESS_ID, solver_name),
        process_id=DEFAULT_FLOW_PROCESS_ID,
        process_type="flow",
        solver=solver_name,
    )
    plan = SimulationPlan(name=name, description=name, runs=(run_entry,))
    ctx.execution.simulation_plan = plan
    ctx.execution.process_runs_by_id = {run_entry.id: run_entry}
    return plan


def step_apply_flow_overrides(flow, overrides: dict[str, Any]) -> None:
    """Patch homogeneous flow parameters in-place.

    Raises ValueError if an override targets an unknown parameter, listing the
    available keys so calibration loops fail fast.
    """
    for key, value in overrides.items():
        if key not in flow.parameters:
            available = ", ".join(sorted(flow.parameters))
            raise ConfigError(f"Unknown parameter '{key}'. Available: {available}")
        flow.parameters[key].value = value


def step_rebuild_domain(ctx: WorkflowContext, *, thickness: float) -> Domain:
    """Rebuild the Domain with a new aquifer thickness.

    Reapplies catchment zones and geology binders so the returned Domain is
    fully hydrated. Does not mutate ctx.setup.domain; the caller stores the
    result once the run consumes it.
    """
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.spatial.geographic.structure_binders import (
        apply_catchment_zones_to_domain,
        apply_geology_to_domain,
    )

    domain_cfg = ctx.cfg.domain.model_copy(deep=True)
    domain_cfg.depth_model.thickness = thickness
    surface_topo = ctx.setup.geographic_features.surface_topo
    domain = Domain(config=domain_cfg, surface_topo=surface_topo)
    apply_catchment_zones_to_domain(
        domain=domain,
        geographic=ctx.setup.domain_geographic,
    )
    if ctx.loaded_data.geology is not None:
        apply_geology_to_domain(
            domain=domain,
            geology=ctx.loaded_data.geology,
        )
    return domain


def _default_flow_solver(ctx: WorkflowContext) -> str:
    """Resolve the flow solver name from cfg.simulation.process."""
    for proc in ctx.cfg.simulation.process or ():
        if proc.type == "flow" and proc.solvers:
            return proc.solvers[0]
    engine = getattr(getattr(ctx.cfg, "solver", None), "backend_name", None)
    if engine:
        return str(engine)
    raise ConfigError("No flow solver declared in simulation.process or solver.backend")


# ---------------------------------------------------------------------------
# Results-config alignment
# ---------------------------------------------------------------------------


# Derived fields computed from the per-cell budget group. They are impossible
# to build unless ``budget.spatial_fields`` persisted that group.
BUDGET_DEPENDENT_DERIVED: tuple[str, ...] = (
    "release_flux",
    "accumulation_flux",
    "release_accumulation_flux",
    "outflow_drain",
    "mass_seepage",
)

# Dotted path of the per-cell budget switch, as written in the TOML.
BUDGET_SPATIAL_FLAG = "budget.spatial_fields"

# Derived fields of the solute chain. Each one is built from the concentration
# field, so a plan with no solute-transport run can produce none of them.
SOLUTE_DERIVED: tuple[str, ...] = (
    "concentration_seepage",
    "mass_seepage",
    "mass_accumulated",
)

# Adapter capability that marks a run able to produce a solute concentration
# field (GWT, MT3DMS). Particle tracking (MODPATH, MF6 PRT) is a transport
# process too, but it carries pathlines, not concentrations.
SOLUTE_CONCENTRATION_CAPABILITY = "transport:concentration"

# Solvers whose seepage is an explicit surface-release flux stored in
# ``budget/surface_excess``. On those the geometric criterion (water table at
# or above the surface) over-reports, so the budget is what keeps the physics.
SURFACE_EXCESS_SOLVERS: frozenset[str] = frozenset({"boussinesq"})


@dataclass(frozen=True, slots=True)
class ReconciledResults:
    """Results config aligned with the plan, plus what reconciliation forced.

    ``forced_flags`` holds the dotted config paths reconciliation turned on
    by itself. They are computed means, not user choices, so the run may drop
    a heavy one once it has served its purpose. A flag the user wrote in the
    TOML never appears here.
    """

    config: ResultsConfig
    forced_flags: tuple[str, ...] = ()

    @property
    def budget_is_intermediate(self) -> bool:
        """True when the per-cell budget was forced on, not asked for."""
        return BUDGET_SPATIAL_FLAG in self.forced_flags


def step_configure_results(
    user_cfg: ResultsConfig,
    plan: SimulationPlan,
    display: DisplayConfig,
    *,
    display_active: bool = True,
) -> ReconciledResults:
    """Return a ResultsConfig aligned with the plan and the requested figures.

    A figure listed in ``display.figures`` is an explicit request: the derived
    fields it declares are turned on so the tool computes what it was asked to
    draw. ``display_active`` is the run's effective rendering switch (``hmp run
    --no-display`` turns it off): when nothing will be drawn, no figure gets to
    turn a flag on, so skipping the figures also skips their storage cost.
    Solute-chain derived variables are then disabled when no run of the plan
    can produce a concentration, and whatever survives that pruning turns the
    per-cell budget back on when it cannot be built without it.
    """
    cfg, forced = _reconcile_figure_dependent_derived(
        user_cfg,
        display,
        display_active=display_active,
    )
    if not _plan_produces_concentration(plan):
        cfg = _disable_solute_derived(cfg)
    cfg, budget_forced = _reconcile_budget_consumers(
        cfg,
        plan,
        display,
        display_active=display_active,
    )
    if budget_forced:
        forced = (*forced, BUDGET_SPATIAL_FLAG)
    return ReconciledResults(config=cfg, forced_flags=forced)


def _plan_produces_concentration(plan: SimulationPlan) -> bool:
    """True when one run of the plan can write a solute concentration field.

    The process type alone is not the criterion: particle tracking (MODPATH,
    MODFLOW 6 PRT) is declared as a transport process but produces pathlines,
    never a concentration. Counting it would promise the user a transport run
    that resolves the solute chain, and that run never comes. The adapter
    capability ``transport:concentration`` is what actually answers.
    """
    from hydromodpy.solver.base.registry import capabilities

    return any(
        SOLUTE_CONCENTRATION_CAPABILITY in capabilities(run.process_type, run.solver)
        for run in plan.runs
        if run.process_type == "transport"
    )


def _disable_solute_derived(cfg: ResultsConfig) -> ResultsConfig:
    """Turn the solute-chain derived fields off when nothing computes a solute.

    Concentration is the input of the whole chain, so without a solute
    transport run (GWT, MT3DMS) nothing can produce these fields. Leaving the
    flags on would end in a field the user asked for and never got, so the drop
    is announced with what to add to get it.
    """
    dropped = [name for name in SOLUTE_DERIVED if getattr(cfg.derived, name)]
    if not dropped:
        return cfg
    logger.warning(
        "No solute transport process in this plan: turning [simulation.results.derived] %s off. "
        "Declare a solute transport process (modflow6 GWT, mt3dms) to compute %s.",
        ", ".join(f"{name} = true" for name in dropped),
        "them" if len(dropped) > 1 else "it",
    )
    return cfg.model_copy(
        update={"derived": cfg.derived.model_copy(update=dict.fromkeys(dropped, False))}
    )


def _reconcile_figure_dependent_derived(
    cfg: ResultsConfig,
    display: DisplayConfig,
    *,
    display_active: bool,
) -> tuple[ResultsConfig, tuple[str, ...]]:
    """Enable the ``results.derived`` flags the requested figures need.

    Fields recomputed on the fly from the stored head (water-table elevation
    and depth, seepage mask) are left unpersisted: they are available without
    a flag. Anything else a requested figure declares must be computed, or the
    figure the user asked for would silently disappear from the output.
    Returns the config and the dotted paths this pass turned on.
    """
    if not display_active or not display.enabled or not display.figures:
        return cfg, ()
    from hydromodpy.display import figure_registry
    from hydromodpy.results.derive.config_flags import derived_flag_for
    from hydromodpy.results.derive.virtual_fields import HEAD_DERIVED_VIRTUAL_FIELDS

    updates: dict[str, bool] = {}
    for figure_name in display.figures:
        for field in figure_registry.get(figure_name).spec.required_fields:
            flag = derived_flag_for(field)
            if flag is None or field in HEAD_DERIVED_VIRTUAL_FIELDS:
                continue
            if getattr(cfg.derived, flag) or flag in updates:
                continue
            updates[flag] = True
            logger.info(
                "Figure '%s' needs the '%s' field: enabling "
                "[simulation.results.derived] %s = true.",
                figure_name,
                field,
                flag,
            )
    if not updates:
        return cfg, ()
    forced = tuple(f"derived.{flag}" for flag in sorted(updates))
    return cfg.model_copy(update={"derived": cfg.derived.model_copy(update=updates)}), forced


def _reconcile_budget_consumers(
    cfg: ResultsConfig,
    plan: SimulationPlan,
    display: DisplayConfig,
    *,
    display_active: bool,
) -> tuple[ResultsConfig, bool]:
    """Force ``budget.spatial_fields`` on when something in the run needs it.

    The per-cell budget is off by default. Silently keeping it off would turn a
    requested derived field into a no-op, a requested figure into a silent skip,
    or a Boussinesq seepage mask into its geometric approximation, so the
    request wins. The group is an intermediate here: it is written, consumed by
    the derivation and by the figures, then dropped before the run is sealed.
    Returns the config and whether the switch was flipped.
    """
    if cfg.budget.spatial_fields:
        return cfg, False
    reasons = _budget_consumers(cfg, plan, display, display_active=display_active)
    if not reasons:
        return cfg, False
    logger.info(
        "%s need the per-cell budget: computing it as an intermediate "
        "(dropped from the store once the derived fields and the figures are written).",
        "; ".join(reasons),
    )
    updated = cfg.model_copy(
        update={"budget": cfg.budget.model_copy(update={"spatial_fields": True})}
    )
    return updated, True


def _budget_consumers(
    cfg: ResultsConfig,
    plan: SimulationPlan,
    display: DisplayConfig,
    *,
    display_active: bool,
) -> list[str]:
    """Name every consumer of this run that reads the per-cell budget."""
    reasons: list[str] = []
    derived = [name for name in BUDGET_DEPENDENT_DERIVED if getattr(cfg.derived, name)]
    if derived:
        reasons.append(f"results.derived {', '.join(derived)}")
    figure_fields = _figure_budget_fields(display, display_active=display_active)
    if figure_fields:
        reasons.append(f"requested figure field(s) {', '.join(figure_fields)}")
    if _seepage_needs_surface_excess(cfg, plan, display, display_active=display_active):
        reasons.append("the seepage mask of a surface-excess solver (budget/surface_excess)")
    return reasons


def _figure_budget_fields(
    display: DisplayConfig,
    *,
    display_active: bool,
) -> tuple[str, ...]:
    """Raw budget fields the requested figures read, sorted and deduplicated.

    These fields have no ``results.derived`` flag of their own: the budget
    group is their only switch, so a figure declaring one is a request for
    the group.
    """
    from hydromodpy.display import figure_registry
    from hydromodpy.results.field_registry import FIELD_REGISTRY

    if not display_active or not display.enabled or not display.figures:
        return ()
    wanted: set[str] = set()
    for figure_name in display.figures:
        for field in figure_registry.get(figure_name).spec.required_fields:
            descriptor = FIELD_REGISTRY.get(field)
            if descriptor is not None and descriptor.zarr_path.startswith("budget/"):
                wanted.add(field)
    return tuple(sorted(wanted))


def _seepage_needs_surface_excess(
    cfg: ResultsConfig,
    plan: SimulationPlan,
    display: DisplayConfig,
    *,
    display_active: bool,
) -> bool:
    """True when a seepage mask is requested on a surface-excess solver.

    Those solvers release water through ``budget/surface_excess``; without it
    the mask degrades to the geometric criterion, which over-reports. Keeping
    the physics means computing the budget, so the mask reads the flux.
    """
    if not any(str(run.solver) in SURFACE_EXCESS_SOLVERS for run in plan.runs):
        return False
    if cfg.derived.seepage_areas:
        return True
    if not display_active or not display.enabled or not display.figures:
        return False
    from hydromodpy.display import figure_registry

    return any(
        "seepage_mask" in figure_registry.get(name).spec.required_fields for name in display.figures
    )
