"""Planning step - build a SimulationPlan and decide the per-cell budget it keeps."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from hydromodpy.core.budget.terms import SURFACE_EXCESS_TERM, BudgetKeep, budget_terms_for_fields
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.exporters.export_spec import ExportRequest
    from hydromodpy.solver.base.observation_config import ObservationConfig
    from hydromodpy.solver.base.plan import SimulationPlan
    from hydromodpy.solver.base.results_config import ResultsConfig

logger = get_logger(__name__)


DEFAULT_FLOW_PROCESS_ID = "flow_main"


def step_build_plan(ctx: WorkflowContext, *, name: str) -> SimulationPlan:
    """Build the SimulationPlan of the run from ``ctx.cfg.simulation``.

    An override of the run is already in ``ctx.cfg``, so the plan and the sealed
    configuration describe one run. Sets ``ctx.setup.run_id``,
    ``ctx.execution.simulation_plan`` and the process-run map.
    """
    from hydromodpy.solver.base.planner import SimulationPlanner

    plan = SimulationPlanner().build(ctx.cfg.simulation)
    ctx.setup.run_id = name
    ctx.execution.simulation_plan = plan
    ctx.execution.process_runs_by_id = {r.id: r for r in plan.runs}
    return plan


# ---------------------------------------------------------------------------
# Per-cell budget of the run
# ---------------------------------------------------------------------------


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
    level: str = "result",
    display_active: bool,
    export_requests: Sequence[ExportRequest],
    calibration: CalibrationConfig | None,
    observation: ObservationConfig | None,
    lightweight: bool = False,
) -> BudgetKeep:
    """Return the per-cell budget terms this run keeps.

    ``level`` is read from the lineage of the run. A kept calibration trial is
    ``research``: it keeps only the terms its criterion reads, those of
    ``[calibration.outputs]`` and the seepage mask of a surface-excess solver,
    whatever ``keep_per_cell_budget`` asks. It draws no figure and writes no
    export, so no other consumer of its budget exists.

    Every other run is ``result`` and follows the rules below.
    ``[simulation.results] keep_per_cell_budget = true`` (the default) keeps
    every term the extractor produces. ``false`` keeps the union of the terms
    the declared consumers read: the figures of ``[display].figures`` and the
    overlays they ask for (when ``display.enabled``, and not for a calibration
    trial, which draws nothing: ``display_active`` is false), the ``[[export]]``
    requests, the calibration outputs, the variables of the ``[observation]``
    points, and the seepage mask of a surface-excess solver. ``hmp run
    --no-display`` is a choice of the launch: it draws nothing now and keeps what
    the figures read, so the data of a run depend on its configuration alone and
    ``hmp export <run> --regen figures`` can draw them later. ``lightweight`` is a calibration trial:
    it logs the decision at DEBUG, not INFO.
    """
    if level != "research" and results.keep_per_cell_budget:
        return BudgetKeep.everything()
    consumers: dict[str, list[str]] = {}

    def _add(fields: Iterable[str], consumer: str) -> None:
        for term in budget_terms_for_fields(fields):
            names = consumers.setdefault(term, [])
            if consumer not in names:
                names.append(consumer)

    if level != "research":
        if display_active and display.enabled:
            import hydromodpy.display.figure_registry as figure_registry

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
    if level != "research" and observation is not None:
        for point in observation.declarations():
            _add(
                tuple(str(name) for name in point["variables"]),
                f"[[observation.points]] {point['id']!r}",
            )
    if _plan_has_surface_excess(plan):
        _add((SURFACE_EXCESS_TERM,), "the seepage mask of a surface-excess solver")

    keep = BudgetKeep.of_terms(consumers)
    described = (
        "; ".join(f"{term} ({', '.join(consumers[term])})" for term in sorted(consumers))
        or "no term"
    )
    if level == "research":
        logger.debug(
            "A kept calibration trial keeps only the per-cell budget terms its criterion "
            "reads (policy %r): %s.",
            keep.policy,
            described,
        )
        return keep
    log = logger.debug if lightweight else logger.info
    log(
        "[simulation.results] keep_per_cell_budget = false: the run keeps the per-cell "
        "budget its consumers read (policy %r): %s.",
        keep.policy,
        described,
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
    """True when one solver run of the plan writes the surface-excess flux.

    A solver whose seepage is an explicit surface-release flux lists
    ``budget/surface_excess`` in its ``writes``. Its seepage mask is rebuilt
    from that term, so a run that keeps only what its consumers read still
    keeps it.
    """
    from hydromodpy.results.field_registry import BUDGET_GROUP
    from hydromodpy.solver.base.registry import solvers

    written = f"{BUDGET_GROUP}{SURFACE_EXCESS_TERM}"
    return any(
        written in solvers.get(run.process_type, run.solver).writes
        for run in plan.runs
        if run.is_solver_backed
    )
