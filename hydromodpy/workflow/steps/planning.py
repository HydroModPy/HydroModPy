"""Planning step - build a SimulationPlan and decide the per-cell budget it keeps."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from hydromodpy.core.budget_terms import SURFACE_EXCESS_TERM, BudgetKeep, budget_terms_for_fields
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.core.config_kit.export_spec import ExportRequest
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.simulation.planning.observation_config import ObservationConfig
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.simulation.planning.results_config import ResultsConfig

logger = get_logger(__name__)


DEFAULT_FLOW_PROCESS_ID = "flow_main"


def resolve_run_config(cfg: Any, *, thickness: float | None) -> Any:
    """Return the configuration this run is defined by.

    An override of a declared value belongs to the configuration of the run,
    not to an object built from it. The domain is built from ``cfg.domain`` by
    every path that builds it - a fresh run, a prefix reconstruction after a
    process death, another process entirely - so a thickness patched onto the
    built ``Domain`` is lost the next time one of them runs, and the
    configuration the run archives beside its results describes a run that
    never happened.

    The returned configuration shares every section with ``cfg`` except the one
    an override touches, so a run that overrides nothing gets ``cfg`` itself,
    and the domain section is an object identity a later run can compare against
    what built its geometry. A deep copy of the whole configuration would detach
    the sections a Project resolved once at load time and still hands around.

    ``model_copy(update=...)`` does not re-run the cross-section validators of
    ``HydroModPyConfig``, and none of them reads ``domain``: the copy is as
    valid as the configuration it derives from. A section any of them does read
    - ``flow``, ``solver``, ``transport``, ``calibration``, ``data`` - cannot be
    folded in this way without validating the result.
    """
    if thickness is None:
        return cfg
    kind = cfg.domain.depth_model.kind
    if kind != "constant_thickness":
        # Assigning the field on another kind raised a raw Pydantic error.
        raise ConfigError(
            f"thickness overrides domain.depth_model.thickness, and depth_model kind "
            f"{kind!r} has no thickness. Change [domain.depth_model] in the "
            "configuration instead."
        )
    domain_cfg = cfg.domain.model_copy(deep=True)
    domain_cfg.depth_model.thickness = thickness
    return cfg.model_copy(update={"domain": domain_cfg})


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

    ``thickness`` is read here only to know that this run is a single-process
    parameter probe: its value is already resolved into ``ctx.cfg`` by
    :func:`resolve_run_config`, and the domain builder reads it there.
    """
    if overrides or thickness is not None or first_clim is not None:
        return _build_plan_with_overrides(
            ctx,
            name=name,
            overrides=overrides or {},
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

    ctx.setup.flow = flow
    ctx.setup.run_id = name

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
# Per-cell budget of the run
# ---------------------------------------------------------------------------


# A solver whose seepage is an explicit surface-release flux stored in
# ``budget/surface_excess`` declares it. Its seepage mask is rebuilt from that
# term, so a run that keeps only what its consumers read still keeps it.
SURFACE_EXCESS_CAPABILITY = "flow:surface_excess"

# Overlays of ``[display.overrides.<figure>] overlays`` that read a field.
_OVERLAY_FIELDS: dict[str, tuple[str, ...]] = {
    "seepage": ("seepage_mask",),
    "wells": ("well",),
}

# What a calibration output support asks the backend for, beyond its variable.
_CALIBRATION_FIELDS_BY_SUPPORT: dict[str, tuple[str, ...]] = {
    "network": ("release_flux",),
}


def step_configure_results(
    results: ResultsConfig,
    plan: SimulationPlan,
    display: DisplayConfig,
    *,
    display_active: bool,
    export_requests: Sequence[ExportRequest],
    calibration: CalibrationConfig | None,
    observation: ObservationConfig | None,
    lightweight: bool = False,
) -> BudgetKeep:
    """Return the per-cell budget terms this run keeps.

    ``[simulation.results] keep_per_cell_budget = true`` (the default) keeps
    every term the extractor produces. ``false`` keeps the union of the terms
    the declared consumers read: the figures of ``[display].figures`` and the
    overlays they ask for (only when ``display_active`` and ``display.enabled``;
    ``hmp run --no-display`` turns it off), the ``[[export]]`` requests, the
    calibration outputs, the variables of the ``[observation]`` points, and the
    seepage mask of a surface-excess solver. ``lightweight`` is a calibration
    trial: it logs the decision at DEBUG, not INFO.
    """
    if results.keep_per_cell_budget:
        return BudgetKeep.everything()
    consumers: dict[str, list[str]] = {}

    def _add(fields: Iterable[str], consumer: str) -> None:
        for term in budget_terms_for_fields(fields):
            names = consumers.setdefault(term, [])
            if consumer not in names:
                names.append(consumer)

    if display_active and display.enabled:
        from hydromodpy.display import figure_registry

        for figure_name in display.figures:
            spec = figure_registry.get(figure_name).spec
            _add((*spec.required_fields, *spec.optional_fields), f"figure {figure_name!r}")
            for overlay in _requested_overlays(display, figure_name):
                _add(
                    _OVERLAY_FIELDS.get(overlay, ()),
                    f"overlay {overlay!r} of {figure_name!r}",
                )
    for request in export_requests:
        _add(request.names, "[[export]]")
    if calibration is not None:
        for name, output in (calibration.outputs or {}).items():
            support = str(getattr(output, "support", ""))
            fields = (
                *_CALIBRATION_FIELDS_BY_SUPPORT.get(support, ()),
                str(getattr(output, "variable", "") or ""),
            )
            _add(fields, f"calibration output {name!r}")
    if observation is not None:
        for point in observation.declarations():
            _add(
                tuple(str(name) for name in point["variables"]),
                f"[[observation.points]] {point['id']!r}",
            )
    if _plan_has_surface_excess(plan):
        _add((SURFACE_EXCESS_TERM,), "the seepage mask of a surface-excess solver")

    keep = BudgetKeep.of_terms(consumers)
    log = logger.debug if lightweight else logger.info
    log(
        "[simulation.results] keep_per_cell_budget = false: the run keeps the per-cell "
        "budget its consumers read (policy %r): %s.",
        keep.policy,
        "; ".join(f"{term} ({', '.join(consumers[term])})" for term in sorted(consumers))
        or "no term",
    )
    return keep


def _requested_overlays(display: DisplayConfig, figure_name: str) -> tuple[str, ...]:
    """Return the overlays ``[display.overrides.<figure>]`` asks a figure for."""
    options = display.overrides.get(figure_name) or {}
    overlays = options.get("overlays") if isinstance(options, dict) else None
    if overlays is None:
        return ()
    if isinstance(overlays, str):
        return (overlays,)
    return tuple(str(name) for name in overlays)


def _plan_has_surface_excess(plan: SimulationPlan) -> bool:
    """True when one run of the plan declares a surface-excess flux."""
    from hydromodpy.solver.base.registry import capabilities

    return any(
        SURFACE_EXCESS_CAPABILITY in capabilities(run.process_type, run.solver) for run in plan.runs
    )
