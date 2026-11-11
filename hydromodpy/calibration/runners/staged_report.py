"""The tables and the method sentences a staged calibration writes."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl
from hydromodpy.calibration.config_outputs import CalibOutputDecl
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.metrics.observed_pairing import OBSERVED_FAMILY_BY_VARIABLE
from hydromodpy.calibration.metrics.series import DATA_FAMILY_SECTION
from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST, engine_traits
from hydromodpy.calibration.protocols.registry import (
    deviations_in_force,
    get_protocol,
    protocol_options_away_from_the_recipe,
)
from hydromodpy.calibration.report import (
    CalibrationReport,
    FrozenParameter,
    PhaseRun,
    samples_text,
)
from hydromodpy.calibration.runners.document import declared_window_text
from hydromodpy.calibration.runners.phase_regime import regime_overrides
from hydromodpy.calibration.runners.restarts import unsettled_search
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.solver_config import SolverConfig

logger = get_logger(__name__)


def phase_settled(report: CalibrationReport) -> bool:
    """Whether a phase produced a candidate the next phases can build on.

    Settled, not quality: a coarse agreement still returns a number. What
    disqualifies a phase is having no best candidate at all, a best cost that
    is the failed-evaluation sentinel, a root closed outside the declared bounds
    (a bound is not a solved value, as for ``resume.completed_phases``), or a
    search that spent its budget before a stopping rule of its own was met
    (:func:`~hydromodpy.calibration.optim.stopping.settled`). A root search may
    have been granted, once, the exact halvings it still needed; no other
    engine gets an extension. That last candidate is wherever the budget ended,
    and freezing it would hand the next phase a value the search never settled
    on. A search with no rule of its own settles on its budget: its best is the
    best of a budget-only search, which :func:`_frozen_by` says.
    """
    if report.best_parameters is None or report.best_cost is None:
        return False
    if "root_outside_bounds" in report.extra or unsettled_search(report) is not None:
        return False
    return math.isfinite(report.best_cost) and report.best_cost < FAILED_EVAL_COST


def _length_text(value: Any) -> str:
    """Return a coordinate the way a report reads it: its bare magnitude.

    ``:.10g`` rather than ``str()``: a document written by hand carries a bare
    TOML number, ``0``, and one written by the Python-mode overlay round-trips
    it through a pint string, ``0.0``. Both name the same coordinate, and a
    phase-less comparison table built from either has to read the same either
    way (``tests/unit/api/test_calibrate.py`` compares the two routes).
    """
    if value is None:
        return "?"
    magnitude = getattr(value, "magnitude", value)
    return f"{float(magnitude):.10g}"


def _output_where(output: CalibOutputDecl) -> str:
    """Return where one output reads its simulated value, or '' for a network.

    A network output names no cell of its own: what it is read against is the
    file or the section its source names, which the caller adds as the
    observed source instead.
    """
    support = str(getattr(output, "support", ""))
    if support == "point":
        if getattr(output, "observes", None) is not None:
            # The station's record places it; an x or y written beside it is
            # never read, so it is never printed as where the value comes from.
            return _station_where(output)
        if getattr(output, "geometry", None) is not None:
            return "its declared geometry"
        return f"({_length_text(output.x)}, {_length_text(output.y)})"
    if support == "boundary":
        return f"boundary {output.boundary_id!r}"
    if support == "cell":
        return f"cell (row {output.row}, col {output.col})"
    if support == "lake":
        return f"lake {output.lake_id!r}"
    return ""


def _station_where(output: CalibOutputDecl) -> str:
    """Return where a point output that observes a station reads its simulated value.

    The same rule the extraction applies
    (:func:`hydromodpy.calibration.metrics.solver_extract.observable_request_for_output`).
    A discharge station is not placed by its coordinate, so without a snap it
    is scored on the whole-catchment series. A snap moves it onto the most
    drained cell near its record. Any other variable is read in the cell its
    record falls in. The cell itself is only known once the mesh exists.
    """
    station = f"station {output.observes}"
    if str(getattr(output, "variable", "")) != "discharge":
        return f"{station} (the cell its record falls in)"
    radius = getattr(output, "snap_radius", None)
    if radius is None:
        return f"{station} (whole-catchment series)"
    metres = radius.to("m") if callable(getattr(radius, "to", None)) else radius
    return f"{station} (the most drained cell within {_length_text(metres)} m of its record)"


def _output_quantity(output: CalibOutputDecl) -> str:
    """Return the simulated quantity one output reads: variable, support, where.

    A point output that observes a station reads ``discharge, station NANCON
    (whole-catchment series)``: the station says where, not the support.
    """
    variable = str(getattr(output, "variable", ""))
    support = str(getattr(output, "support", ""))
    where = _output_where(output)
    if support == "point" and getattr(output, "observes", None) is not None:
        return f"{variable}, {where}"
    return f"{variable} ({support}, {where})" if where else f"{variable} ({support})"


def _observed_source(output: CalibOutputDecl) -> str:
    """Return what one output is compared against.

    A station and its ``[data.<family>]`` section for an output that
    ``observes`` one; the file or the mapped source for a network output;
    what ``observed_values`` carries otherwise.
    """
    observes = getattr(output, "observes", None)
    if observes is not None:
        variable = str(getattr(output, "variable", ""))
        family = OBSERVED_FAMILY_BY_VARIABLE.get(variable)
        section = DATA_FAMILY_SECTION.get(family) if family else None
        return f"station {observes} ([data.{section}])" if section else f"station {observes}"
    if str(getattr(output, "support", "")) == "network":
        return str(output.map.complete)
    values = getattr(output, "observed_values", None)
    if values is not None:
        return f"{len(values)} value(s) written in the file"
    return "nothing declared"


def _block_row(
    outputs: Mapping[str, CalibOutputDecl], block: CalibObjectiveBlockDecl, share: float
) -> dict[str, Any]:
    """Return one row for a declared block: its criterion, share, and comparison."""
    used = [name for name in block.uses_outputs if name in outputs]
    return {
        "block": block.name,
        "metric": str(block.metric),
        "share": share,
        "quantity": "; ".join(_output_quantity(outputs[name]) for name in used),
        "source": "; ".join(_observed_source(outputs[name]) for name in used),
    }


def _single_metric_row(cfg: CalibrationConfig, phase: CalibPhaseDecl | None) -> dict[str, Any]:
    """Return the one row of the single-metric route: 'variable' scored by 'objective'."""
    variable = str((phase.variable if phase is not None else None) or cfg.variable)
    objective = str((phase.objective if phase is not None else None) or cfg.objective)
    family = OBSERVED_FAMILY_BY_VARIABLE.get(variable)
    section = DATA_FAMILY_SECTION.get(family) if family else None
    where = f"[data.{section}]" if section else "the loaded records"
    source = f"the station [site] gauge names, else every loaded station ({where})"
    return {
        "block": None,
        "metric": objective,
        "share": 1.0,
        "quantity": f"{variable}, at the station(s) the project loads",
        "source": source,
    }


def objective_comparison_table(
    cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None
) -> list[dict[str, Any]]:
    """Return, for a phase or the whole section, what each block compares with what.

    One row per declared block, in declaration order: its criterion
    (``metric``), its normalized share (:meth:`CalibrationConfig.objective_blocks_for`,
    divided by the sum, as :class:`optim.objective.CompositeObjective`
    normalizes its own weights), the simulated quantity each of its outputs
    reads, and what it is compared against. A phase that declares no block, or
    a phase-less calibration with none either, takes the single-metric route
    instead: one row for 'variable' scored by 'objective'.

    Reads declarations only, no project data: this is what lets
    ``--list-phases`` build it without the data on disk, and is why
    ``hmp check`` can show it for a plain calibration's one search, which
    ``--list-phases`` has no phase to attach it to.
    """
    single_metric = phase.is_single_metric if phase is not None else not cfg.objective_blocks
    if single_metric:
        return [_single_metric_row(cfg, phase)]
    weighted = cfg.objective_blocks_for(phase)
    if not weighted:
        return []
    outputs = cfg.outputs or {}
    total = sum(weight for _, weight in weighted)
    return [
        _block_row(outputs, block, weight / total if total > 0 else 0.0)
        for block, weight in weighted
    ]


def _search_rows(cfg: CalibrationConfig, decl: Any, method: str) -> dict[str, dict[str, Any]]:
    """Return the four search keys of a phase, each with its value and where it comes from."""
    sources = cfg.search_sources_for(decl)
    values = {
        "method": method,
        "max_trials": cfg.max_trials_for(decl),
        "precision": cfg.precision_for(decl),
        "method_options": cfg.method_options_for(decl),
    }
    return {key: {"value": values[key], "source": sources[key]} for key in values}


def phase_summaries(cfg: CalibrationConfig | None) -> list[dict[str, Any]]:
    """Describe the declared phases in declaration order, without running anything.

    ``method`` is the method the phase runs. A phase that names none, in itself
    or in ``[calibration]``, also carries ``method_reason``, why its criteria
    call for that one. ``search`` gives the value of ``method``, ``max_trials``,
    ``precision`` and ``method_options`` the phase runs with, each with where it
    comes from: the phase, the section, or the default.
    ``interval_width`` is the width the phase reads its interval with and where
    it comes from (``IntervalWidth.to_dict``); one mesh cell has no number
    before the mesh exists.

    A phase that lists a parameter an earlier phase passes on also carries
    ``reopens``, each such parameter with the phase it comes from, and
    ``starts_from_passed_values``, whether its engine takes a start point. A
    phase that re-opens nothing carries neither key. The earlier phase is the
    latest one before it that declares ``freeze_on_success`` on the same path,
    under any parameter name; at run time it passes its values on only if it
    converges.

    ``comparisons`` is :func:`objective_comparison_table` for that phase: what
    each of its blocks, or its single metric, compares with what.
    ``window`` says in words the window the phase scores on.
    """
    rows: list[dict[str, Any]] = []
    passed_by: dict[str, str] = {}
    declared = cfg.parameters if cfg is not None else {}

    def written_at(name: str) -> str:
        return declared[name].resolve_target() or name

    for decl in getattr(cfg, "phases", None) or []:
        method, reason = cfg.method_for(decl)
        row: dict[str, Any] = {
            "name": decl.name,
            "description": decl.description,
            "method": method,
            "parameters": list(decl.parameters),
            "depends_on": decl.depends_on,
            "freeze_on_success": decl.freeze_on_success,
        }
        if reason is not None:
            row["method_reason"] = reason
        reopens = [
            {"parameter": name, "from_phase": passed_by[written_at(name)]}
            for name in decl.parameters
            if written_at(name) in passed_by
        ]
        if reopens:
            row["reopens"] = reopens
            row["starts_from_passed_values"] = engine_traits(method).accepts_a_start_point
        if decl.bounds:
            row["bounds"] = {name: list(interval) for name, interval in decl.bounds.items()}
        row["search"] = _search_rows(cfg, decl, method)
        row["interval_width"] = cfg.interval_width_for(decl).to_dict()
        row["comparisons"] = objective_comparison_table(cfg, decl)
        row["window"] = declared_window_text(cfg, decl)
        rows.append(row)
        if decl.freeze_on_success:
            passed_by.update({written_at(name): decl.name for name in decl.parameters})
    return rows


def backend_name(document: Mapping[str, Any]) -> str:
    """Return the flow solver the trials run, read from the raw document.

    The run builds the solver of the flow process of ``[[simulation.process]]``,
    and validation makes ``solver.backend`` follow it. So the first solver of
    the first flow process wins; a document without one runs the backend of
    ``[solver]``, or the default backend when that is left out too.
    """
    simulation = document.get("simulation")
    processes = simulation.get("process") if isinstance(simulation, Mapping) else None
    for process in processes if isinstance(processes, list | tuple) else ():
        if not isinstance(process, Mapping):
            continue
        if str(process.get("kind", "")).strip().lower() != "flow":
            continue
        solvers = process.get("solvers")
        names = [str(name).strip() for name in solvers or () if str(name).strip()]
        if names:
            return names[0]
    solver = document.get("solver")
    declared = solver.get("backend") if isinstance(solver, Mapping) else None
    if isinstance(declared, str) and declared.strip():
        return declared.strip().lower()
    return SolverConfig().backend_name


_GEOGRAPHIC_DEVIATIONS = ("dem_correc_type",)
"""Keys a protocol departs on that live under ``[geographic]``, not on an output."""


def _declares_conditioned_dem(document: Mapping[str, Any]) -> bool:
    """True when any ``[[data.dem.sources]]`` entry declares ``state = "conditioned"``."""
    data = document.get("data")
    dem = data.get("dem") if isinstance(data, Mapping) else None
    sources = dem.get("sources") if isinstance(dem, Mapping) else None
    return any(
        isinstance(source, Mapping) and source.get("state") == "conditioned"
        for source in sources or ()
    )


def geographic_choices(document: Mapping[str, Any]) -> dict[str, object]:
    """Return the ``[geographic]`` values the file wrote on a key the protocol departs on.

    Read from the raw document, as the backend is: a key present there is one
    the file set, after ``base_config`` and the legacy migrations. A key left
    unset takes the model's default, which the deviation table already
    describes, so it stays out of the Methods paragraph.

    A ``capped_breach`` is not reproducible without its limits, so the value
    names them, defaults included. A DEM declared ``conditioned`` was filled or
    breached outside HydroModPy, so the regional method reads ``provided`` and
    the solver grid is filled on its own template.
    """
    geographic = document.get("geographic")
    if not isinstance(geographic, Mapping):
        return {}
    chosen = {key: geographic[key] for key in _GEOGRAPHIC_DEVIATIONS if key in geographic}
    if _declares_conditioned_dem(document):
        chosen["dem_correc_type"] = "provided (conditioned outside HydroModPy); solver grid filled"
    if chosen.get("dem_correc_type") == "capped_breach":
        from hydromodpy.catchment.preprocess.capped_breach_config import CappedBreachConfig

        section = geographic.get("capped_breach")
        limits = CappedBreachConfig.model_validate(dict(section) if section else {})
        chosen["dem_correc_type"] = (
            f"capped_breach (max_depth = {float(limits.max_depth):g} m, "
            f"max_distance = {float(limits.max_distance):g} m)"
        )
    return chosen


def steady_window_summary(
    cfg: CalibrationConfig,
    runs: list[PhaseRun],
    document: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the steady window the first ``regime = "steady"`` phase averaged over.

    Read back from :func:`hydromodpy.calibration.runners.phase_regime.regime_overrides`,
    the same translation ``_phase_plans`` already used to run that phase's
    trials: this reports the window the model actually ran with, not a second
    reading of the file that could drift from it. ``None`` when no phase
    declares a steady regime, or when the window cannot be resolved (the same
    case ``_phase_plans`` would have refused before the first solve).

    The mean recharge is reconstructed from ``k_optim_m_s / k_over_r`` on that
    phase's own report, the two values the network criterion already publishes
    there when the phase moved a homogeneous conductivity alone; it is left out
    when either is absent rather than recomputed from the model, which this
    module does not hold onto after the phase returns.
    """
    if not cfg.phases:
        return None
    steady = next((phase for phase in cfg.phases if phase.regime == "steady"), None)
    if steady is None:
        return None
    try:
        overrides = regime_overrides(steady, document)
    except ValueError:
        return None
    start = overrides["simulation.time.start_datetime"]
    end = overrides["simulation.time.end_datetime"]
    days = int(overrides["simulation.time.step_value"])
    if days < 365:
        logger.warning(
            "Phase %s averages recharge over a steady window of %d day(s), %s to %s, "
            "under a year: a partial year biases the mean recharge toward whichever "
            "season it covers.",
            steady.name,
            days,
            start,
            end,
        )
    window: dict[str, Any] = {"start": start, "end": end, "days": days}
    run = next((run for run in runs if run.name == steady.name), None)
    if run is not None:
        k_over_r = run.report.extra.get("k_over_r")
        k_optim = run.report.extra.get("k_optim_m_s")
        if k_over_r and k_optim is not None:
            window["mean_recharge_m_s"] = float(k_optim) / float(k_over_r)
    return window


def methods_paragraph_for(
    cfg: CalibrationConfig,
    runs: list[PhaseRun],
    frozen: list[FrozenParameter],
    raw: Mapping[str, Any] | None = None,
    *,
    backend: str | None = None,
    steady_window: Mapping[str, Any] | None = None,
    geographic: Mapping[str, object] | None = None,
) -> str | None:
    """Return the Methods prose for the stages that actually completed.

    ``geographic`` carries the ``[geographic]`` values the file set on a key
    the protocol departs on (:func:`geographic_choices`). A network output
    never declares those keys, so the two sources cannot disagree.
    """
    from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

    if cfg.protocol is None:
        return None
    completed = [run.name for run in runs if phase_settled(run.report)]
    calibrated = {item.name: float(item.value) for item in frozen}
    # Every option a deviation is declared on, on the output the protocol scores.
    chosen: dict[str, object] = {}
    metrics_window = (raw.get("metrics") or {}).get("window") if isinstance(raw, Mapping) else None
    in_force = deviations_in_force(cfg, None, metrics_window)
    protocol = get_protocol(cfg.protocol.name)
    conditional_keys = {item.key for item in protocol.deviations if item.holds is not None}
    conditional_in_force = [
        item.key for item in in_force if item.key in conditional_keys and item.state == "departs"
    ]
    held = {
        key: float(value)
        for run in runs
        if not phase_settled(run.report)
        for key, value in (run.report.best_parameters or {}).items()
    }
    for item in in_force:
        value = item.value
        if value is None:
            continue
        # A length is a pint quantity; the paragraph prints it in meters.
        if callable(getattr(value, "to", None)):
            value = f"{float(value.to('m').magnitude):g} m"
        chosen[item.key] = value
    for key, value in (geographic or {}).items():
        chosen.setdefault(key, value)
    conditional_widths = {
        run.name: run.report.extra["parameter_uncertainty_note"]
        for run in runs
        if run.report.extra.get("parameter_uncertainty_note")
    }
    absent_widths = {
        run.name: run.report.extra["parameter_uncertainty_absent_note"]
        for run in runs
        if run.report.extra.get("parameter_uncertainty_absent_note")
    }
    paragraph = methods_paragraph(
        cfg.protocol.name,
        stages_that_ran=completed,
        calibrated=calibrated or None,
        chosen=chosen or None,
        options=protocol_options_away_from_the_recipe(cfg.protocol.name, cfg.protocol) or None,
        conditional_widths=conditional_widths or None,
        absent_widths=absent_widths or None,
        backend=backend,
        steady_window=steady_window,
        version=cfg.protocol.version,
        held=held or None,
        stages_declared=len(getattr(cfg, "phases", None) or ()) or None,
        conditional_in_force=conditional_in_force,
    )
    scoring = _scoring_sentence(runs)
    return paragraph if scoring is None else f"{paragraph}\n\n{scoring}"


def _scoring_sentence(runs: Sequence[PhaseRun]) -> str | None:
    """Say what each stage minimized: its metric, and the pairs of its best cost.

    Read off the report of each stage (``cost_metric``, ``cost_samples``,
    ``cost_window``), so the dates are the ones the cost rests on, not the rule
    of the protocol. A stage that counted no pair gives its declared window.
    """
    clauses = []
    for position, run in enumerate(runs, start=1):
        extra = run.report.extra or {}
        metric = extra.get("cost_metric")
        if not metric:
            continue
        clause = f"stage {position} ({run.name}) minimised {metric}"
        window = extra.get("cost_window")
        if extra.get("cost_samples"):
            clause += f" on {samples_text(extra['cost_samples'])}, at its best trial"
            clause += f" ({window})" if window else ""
        elif window and str(window).startswith("window"):
            clause += f" over the {window}, pairs not counted"
        clauses.append(clause)
    if not clauses:
        return None
    return "Scoring: " + "; ".join(clauses) + "."
