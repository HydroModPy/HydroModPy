"""Calibration run in phases: each stage calibrates, then passes its values on.

A staged calibration runs the phases of ``[[calibration.phases]]`` in
declaration order. Each phase is an ordinary mono-phase calibration: it gets
its own configuration, its own optimizer, its own session, and goes through
:func:`hydromodpy.calibration.runners.cli_runner.run_calibration_core` like
any other. What staging adds is what happens between two phases.

Passing values on
-----------------
A phase moves the parameters it lists. Every other parameter holds the last
value an earlier settled phase passed on, otherwise the value of the model
file. A phase passes its values on when it declares ``freeze_on_success`` and
its search settled (:func:`hydromodpy.calibration.optim.stopping.settled`):
its engine met its own rule or exhausted its plan, or, for an engine with no
rule of its own such as a random search, spent its budget. That last phase
passes on the best of a budget-only search and says so, in its descriptor,
in ``session.json`` and on the console. A phase whose engine has a rule the
budget stopped first passes nothing on. A held value is written once into the baseline configuration every
trial of the phase forks from. It is not in that phase's parameter space,
because the phase does not list it.

A phase that lists a parameter an earlier phase passed on moves it again. The
passed value is not written into its baseline, so no trial overwrites what the
search proposes. The search starts from that value when the engine declares
``accepts_a_start_point``; the other coordinates of that start are the sampling
center. An engine that takes no start point keeps its own start. When two
phases pass on the same parameter, the latest wins, and the report names both:
``frozen`` lists each of them, and the later phase lists the value it re-opened.

One session
-----------
The phases share one session, ``sessions/<case>/``: one ``trials.jsonl``
numbered across phases and restarts, one ``phases/<phase>/session.json`` per
phase with its status, its frozen values and its best trial. The best trial of
the last phase is promoted to ``runs/<case>/`` once, after the last restart;
``promote_phases`` promotes the best of each earlier phase under
``phases/<phase>/best/``. ``hmp calibrate --resume`` reopens the session and
reads back the phases that completed with the same fingerprint.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
    CalibPhaseDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.metrics.observed_pairing import OBSERVED_FAMILY_BY_VARIABLE
from hydromodpy.calibration.metrics.series import DATA_FAMILY_SECTION
from hydromodpy.calibration.optim.cache import context_fingerprints, differing_members
from hydromodpy.calibration.optim.cost_margin import IntervalWidth
from hydromodpy.calibration.optim.objective import (
    cost_block_fractions,
    mean_cost_block_fractions,
)
from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST, engine_traits
from hydromodpy.calibration.optim.parameters import (
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.optim.sampling import search_space_center
from hydromodpy.calibration.persistence import (
    CalibrationPersistence,
    PhaseContext,
)
from hydromodpy.calibration.protocols import (
    deviations_in_force,
    get_protocol,
    protocol_options_away_from_the_recipe,
    protocol_record,
)
from hydromodpy.calibration.report import (
    CalibrationReport,
    FrozenParameter,
    PhaseRun,
    samples_text,
)
from hydromodpy.calibration.runners.cli_runner import (
    SessionScope,
    answered_best,
    attach_a_linearized_width,
    closing_session,
    declared_window_text,
    keep_trial_solves,
    load_calibration_document,
    open_calibration_session,
    parameter_widths,
    promote_and_close,
    refuse_a_phase_another_cost_scored,
    refuse_an_objective_that_is_not_an_entry_point,
    release_session_scratch,
    release_trial_solves,
    run_one_search,
    session_cost_name,
    session_status_of,
)
from hydromodpy.calibration.runners.phase_regime import phase_overrides, regime_overrides
from hydromodpy.calibration.runners.prepared_model import check_the_prepared_model
from hydromodpy.calibration.runners.promotion import promote_phase_best, promotion_name_check
from hydromodpy.calibration.runners.recap import cost_metric_label, write_methods
from hydromodpy.calibration.runners.restarts import RestartSpread, unsettled_search
from hydromodpy.calibration.runners.resume import (
    best_parameters_of,
    completed_phases,
    fingerprint_matches,
    reusable_stage,
)
from hydromodpy.calibration.runners.session import (
    latest_session_dir,
    project_root_for,
    search_windows,
)
from hydromodpy.calibration.runners.state import build_cache_context, space_from_config
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials
from hydromodpy.core.exceptions import CalibrationError, ConfigValidationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.workspace.path_registry import in_run_scratch
from hydromodpy.results.checks import FROZE_BUDGET_ONLY
from hydromodpy.results.session.descriptor import SessionStatus
from hydromodpy.results.session.phase import FrozenValue
from hydromodpy.solver.base.solver_config import SolverConfig, solver_name_of_backend

if TYPE_CHECKING:
    import numpy as np

    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Phase configuration
# ---------------------------------------------------------------------------


def _phase_config(cfg: CalibrationConfig, decl: CalibPhaseDecl) -> CalibrationConfig:
    """Return the mono-phase configuration one phase runs under.

    The phase carries its own search (method, budget, parameters) and selects
    by name from what the calibration declares. An empty selection of outputs
    means the ones its blocks read, and an empty selection of blocks means every
    declared one. A phase declaring its own ``variable`` or ``objective`` takes
    the single-metric route instead: it inherits no block, and keeps only the
    output its variable names, the phase's or the section's. ``phases`` is cleared
    so the sub-run is an ordinary calibration.

    ``objective_blocks`` as a list keeps each named block's declared weight. As a
    table ``{block: share}`` it replaces the selected blocks' weight with the
    phase's own share; ``CompositeObjective`` normalizes it the same way it
    already normalizes a declared weight, so the shares need not sum to one.

    A phase used to inherit every declared output whatever it scored. A
    two-stage file naming a network output for its steady stage and a discharge
    output for its transient one therefore handed each stage the output of the
    other, to be extracted from every trial and to weigh nothing. It was not
    only waste: a stage whose criteria cannot read an inherited output is
    refused, so that file did not run at all.
    """
    # The phase-scoped fields (overrides, regime, steady_window) never enter this
    # payload: they reach prepare_trials through _PhasePlan.overrides. This
    # configuration feeds the params hash, so forwarding one would change the
    # hash of every completed stage and void its cache and its reuse. What the file
    # left unset stays unset, since the hash reads what was written.
    payload = cfg.model_dump(exclude_unset=True)
    # A phase that names no method gets the one its criteria call for, written
    # here so the session, the params hash and the report all read that name.
    payload["method"] = cfg.method_for(decl)[0]
    payload["max_trials"] = cfg.max_trials_for(decl)
    payload["precision"] = cfg.precision_for(decl)
    payload["batch_size"] = cfg.batch_size_for(decl)
    payload["parallel"] = cfg.parallel_for(decl)
    payload["method_options"] = cfg.method_options_for(decl)
    # The phase's own keys over [calibration.uncertainty]: the method, its
    # restarts or its perturbation, and the width the interval is read with.
    payload["uncertainty"] = cfg.uncertainty_for(decl).model_dump()
    if decl.variable is not None:
        payload["variable"] = decl.variable
    if decl.objective is not None:
        payload["objective"] = decl.objective
    if decl.window is not None:
        payload["window"] = decl.window.model_dump()
    if not cfg.validation_scored_by(decl):
        payload.pop("validation_window", None)
    problems = cfg.phase_bounds_problems(decl)
    if problems:
        raise ConfigValidationError(problems[0])
    payload["parameters"] = {name: payload["parameters"][name] for name in decl.parameters}
    for name, interval in (decl.bounds or {}).items():
        payload["parameters"][name]["bounds"] = list(interval)
    if decl.is_single_metric:
        # The extractor prefers blocks over the variable whenever both are
        # present, so a phase inheriting the blocks of another one would be
        # scored on that other criterion without saying so. The output its
        # variable names is kept: it holds the declaration the criterion reads
        # (the maps, the extent table), and the model builds from it the one
        # implicit block the whole-file (objective, variable) route builds.
        variable = payload.get("variable", cfg.variable)
        payload["outputs"] = {
            name: value for name, value in payload.get("outputs", {}).items() if name == variable
        }
        payload["objective_blocks"] = []
    else:
        if isinstance(decl.objective_blocks, dict):
            shares = decl.objective_blocks
            payload["objective_blocks"] = [
                {**block, "weight": shares[block["name"]]}
                for block in payload.get("objective_blocks", [])
                if block["name"] in shares
            ]
        elif decl.objective_blocks:
            selected = set(decl.objective_blocks)
            payload["objective_blocks"] = [
                block for block in payload.get("objective_blocks", []) if block["name"] in selected
            ]
        if decl.outputs:
            payload["outputs"] = {name: payload["outputs"][name] for name in decl.outputs}
        elif decl.objective_blocks:
            read = {name for block in payload["objective_blocks"] for name in block["uses_outputs"]}
            payload["outputs"] = {
                name: value for name, value in payload.get("outputs", {}).items() if name in read
            }
    payload["phases"] = None
    # The protocol wrote these phases; a single phase of it is an ordinary
    # calibration and would otherwise be refused for carrying a method whose
    # stages it no longer declares.
    payload["protocol"] = None
    try:
        return CalibrationConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"phase {decl.name!r} does not describe a runnable calibration: {exc}"
        ) from exc


@dataclass(frozen=True, slots=True)
class _PhasePlan:
    """One selected phase, with the calibration, the space and the model it runs under.

    ``overrides`` is what ``prepare_trials(config_overrides=...)`` writes: the
    paths the phase's regime writes, then the phase's own overrides. ``width``
    is the width the phase reads its interval with, and where it comes from.
    """

    index: int
    decl: CalibPhaseDecl
    config: CalibrationConfig
    space: ParameterSpace
    overrides: dict[str, Any]
    width: IntervalWidth


def _phase_plans(
    cfg: CalibrationConfig,
    selected: Sequence[tuple[int, CalibPhaseDecl]],
    document: Mapping[str, Any],
) -> list[_PhasePlan]:
    """Build every selected phase before the first one runs.

    ``_check_phases`` validates the phase table against the calibration it
    narrows, not against the configuration each phase ends up with, so a phase
    that cannot describe a runnable calibration of its own is only found when
    its turn comes: after the phases before it have spent their whole solve
    budget. Building them all here moves that refusal before the first solve,
    and the loop then runs what was built instead of building it again.

    The regime is read here too, from ``document``, the raw configuration the
    phases belong to: a steady window that cannot be read is refused before the
    first solve as well.
    """
    plans: list[_PhasePlan] = []
    for index, decl in selected:
        phase_cfg = _phase_config(cfg, decl)
        method, reason = cfg.method_for(decl)
        if reason is not None:
            logger.info("Phase %s names no method and runs %s: %s.", decl.name, method, reason)
        try:
            overrides = phase_overrides(decl, document)
        except ValueError as exc:
            raise ConfigValidationError(
                f"phase {decl.name!r} gives regime = {decl.regime!r}, which cannot be "
                f"written: {exc}"
            ) from exc
        try:
            phase_cfg.validate_registry()
        except ValueError as exc:
            raise ConfigValidationError(
                f"phase {decl.name!r} declares a search its optimizer refuses: {exc}"
            ) from exc
        try:
            space = space_from_config(phase_cfg)
        except ValueError as exc:
            raise ConfigValidationError(
                f"phase {decl.name!r} declares a parameter space that cannot be built: {exc}"
            ) from exc
        plans.append(
            _PhasePlan(
                index=index,
                decl=decl,
                config=phase_cfg,
                space=space,
                overrides=overrides,
                width=cfg.interval_width_for(decl),
            )
        )
    return plans


def _injected_paths(
    phase_cfg: CalibrationConfig,
    frozen: list[FrozenParameter],
) -> dict[str, str]:
    """Return the config paths the trial pipeline must treat as varying.

    Three families. The phase's own parameters. The values a previous phase
    froze: a preparation step that reads a frozen path has to re-run per trial,
    otherwise the prepared prefix keeps the value the TOML declared and the
    freeze never reaches the solver. And the phase's own overrides, for the
    A phase's own overrides do NOT belong here: they say what model the phase
    runs, not what varies between its trials, and they reach the pipeline
    through ``prepare_trials(config_overrides=...)`` instead. Listed here they
    would cut the prepared prefix down to nothing.
    """
    paths = resolve_override_paths(phase_cfg)
    for item in frozen:
        if item.path is not None:
            paths[item.name] = item.path
    return paths


# ---------------------------------------------------------------------------
# Freezing
# ---------------------------------------------------------------------------


def _held(frozen: Sequence[FrozenParameter], space: ParameterSpace) -> list[FrozenParameter]:
    """Return the passed values a phase holds fixed: the latest per path, minus what it moves.

    A value the phase moves again is left out. Written into the baseline, it
    would sit under every trial: the sample would overwrite it, or, under
    ``mode="scale"``, multiply it instead of the declared value.
    """
    moved_names = set(space.names)
    moved_paths = {param.effective_path for param in space if param.effective_path is not None}
    return [
        item
        for item in _latest_per_path(frozen).values()
        if item.name not in moved_names and item.path not in moved_paths
    ]


def _reopened(
    frozen: Sequence[FrozenParameter], space: ParameterSpace
) -> tuple[FrozenParameter, ...]:
    """Return the passed values a phase moves again, the latest per path.

    Two parameter names may write the same path. The phase then starts from
    the latest value on that path, whichever name found it, so each item is
    given the parameter this phase moves and keeps the phase that found it.
    """
    latest = _latest_per_path(frozen)
    reopened: list[FrozenParameter] = []
    for param in space:
        item = latest.get(param.effective_path or param.name)
        if item is not None:
            reopened.append(FrozenParameter(parameter=param, value=item.value, phase=item.phase))
    return tuple(reopened)


def _latest_per_path(frozen: Sequence[FrozenParameter]) -> dict[str, FrozenParameter]:
    """Return the last passed value for each path, or for each name without a path."""
    latest: dict[str, FrozenParameter] = {}
    for item in frozen:
        latest[item.path or item.name] = item
    return latest


def _passed_start(
    phase_name: str,
    method: str,
    space: ParameterSpace,
    reopened: Sequence[FrozenParameter],
) -> np.ndarray | None:
    """Return where a phase that moves passed values again starts its search.

    The passed values, and the sampling center for the other parameters. One
    coordinate per parameter of ``space``, in transformed space, as
    ``run_calibration_core(start_at=...)`` reads it. ``None`` when the phase
    re-opens nothing, or when its engine takes no start point: the engine then
    keeps its own start, and the log says so.
    """
    if not reopened:
        return None
    moved = ", ".join(f"{item.name}<-{item.phase}" for item in reopened)
    if not engine_traits(method).accepts_a_start_point:
        logger.info(
            "Phase %s moves %s again. The %s engine takes no start point, so it keeps its own.",
            phase_name,
            moved,
            method,
        )
        return None
    start = search_space_center(space)
    passed = {item.name: item.value for item in reopened}
    for index, param in enumerate(space.parameters):
        if param.name in passed:
            start[index] = param.to_transformed(float(passed[param.name]))
    logger.info("Phase %s moves %s again, starting from the passed values.", phase_name, moved)
    return start


def _freeze_into_baseline(trial_ctx: TrialContext, held: Sequence[FrozenParameter]) -> None:
    """Write the held values into the baseline the phase forks from.

    ``TrialContext.fork`` starts every trial from a deep copy of ``base_cfg``
    and then writes the sampled values in, so a value written here reaches
    every trial of the phase without ever entering its search. The write goes
    through the same helper the fork uses, on a baseline freshly loaded from
    the TOML, so ``mode="scale"`` multiplies the declared value once and
    exactly as the phase that calibrated it did.
    """
    for item in held:
        apply_parameter_to_config(trial_ctx.base_cfg, item.parameter, item.value)


def _settled(report: CalibrationReport) -> bool:
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


def _froze_budget_only(report: CalibrationReport) -> bool:
    """Whether the settled search of a phase is a budget-only one that spent its budget."""
    search = report.extra.get("search")
    return isinstance(search, Mapping) and search.get("stop_state") == "budget_spent"


def _why_unsettled(report: CalibrationReport) -> str:
    """Say why a phase produced nothing to freeze, in the terms a user can act on."""
    if outside := report.extra.get("root_outside_bounds"):
        return (
            f"{outside}. The value is where the search stopped, not a solved value, so "
            "it is not passed on. Widen the declared bounds, or check that the residual "
            "responds to the parameter"
        )
    search = unsettled_search(report)
    if search is None:
        return (
            f"its session {report.session_id} produced no result over {report.n_trials} "
            "trial(s): no best candidate, or a best cost at the failed-evaluation sentinel"
        )
    return (
        f"its session {report.session_id} spent {report.n_trials} trial(s) "
        f"(max_trials = {search.get('max_trials')}, plus {search.get('extension')} granted once) "
        f"before its stopping rule ({search.get('stopping_rule')}) was met, so its best "
        "candidate is where the budget ended, not a settled value. Raise max_trials: a "
        "re-run of the same file replays the trials already solved from the cache. So does a "
        "new precision, seed, method or method_options, for every trial it proposes at "
        "values already solved"
    )


def _frozen_by(
    decl: CalibPhaseDecl,
    report: CalibrationReport,
    declared: ParameterSpace,
) -> tuple[FrozenParameter, ...]:
    """Return what this phase hands to the phases that depend on it."""
    if not decl.freeze_on_success:
        return ()
    if not _settled(report):
        logger.warning(
            "Phase %s did not settle (%s); its parameters stay free for the next phases.",
            decl.name,
            _why_unsettled(report),
        )
        return ()
    if _froze_budget_only(report):
        logger.warning(
            "Phase %s %s: %s has no stopping rule of its own, so it did not converge, and "
            "the %d trial(s) it spent pass on their lowest cost. A larger max_trials may "
            "find a lower one.",
            decl.name,
            FROZE_BUDGET_ONLY,
            report.method,
            report.n_trials,
        )
    values = report.best_parameters or {}
    missing = [name for name in decl.parameters if name not in values]
    if missing:
        raise CalibrationError(
            f"phase {decl.name!r} settled but its best candidate carries no value for "
            f"{missing}; there is nothing to freeze for the phases that depend on it."
        )
    return tuple(
        FrozenParameter(parameter=declared[name], value=float(values[name]), phase=decl.name)
        for name in decl.parameters
    )


#: Why no width exists when the phase itself cannot carry one. Written on both
#: paths - the phase that was solved and the phase that was reused - so the
#: Methods paragraph gives the same reason either way.
_NO_STATION_TO_TAKE_A_WIDTH_FROM = (
    "not attached: none of the outputs this phase scores can name a station, so "
    "there is no residual vector to take a width from"
)


def _attach_linearized_width(
    report: CalibrationReport,
    *,
    phase_cfg: CalibrationConfig,
    phase_name: str,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    frozen: Sequence[FrozenParameter],
) -> CalibrationReport:
    """Attach a linearized width to one phase's report, when the document asks for one.

    ``uncertainty.method`` is declared in ``[calibration.uncertainty]`` for every
    phase (D234 in the campaign decisions), and a phase may write its own: the
    width is built at the end of each phase, from the method, the parameters
    and the outputs THAT PHASE reads -- ``phase_cfg``, which carries them.

    A phase none of whose outputs can name a station cannot structurally carry
    a width. That is refused early, before paying for a call this phase could
    never answer, and the refusal never destroys the report: the search
    already paid for it in solver hours (D231), a width is only ever an
    optional reading of it.

    The line is drawn on what an output CAN declare, not on what it did. An
    output that could have named a station and did not is a document mistake,
    still left to fail loudly the way it always has, by the un-caught call
    below - that is D231's own exception and it is kept intact.
    """
    uncertainty = getattr(phase_cfg, "uncertainty", None)
    if getattr(uncertainty, "method", None) != "linearized":
        return report
    if not _phase_can_carry_a_linearized_width(phase_cfg):
        logger.warning(
            "Phase %s: no linearized width is attached, none of the outputs it scores "
            "can name a station to take residuals from. Use method='cost_profile', or "
            "score an output whose support carries observations.",
            phase_name,
        )
        # The Methods paragraph reads this. A width that was never built has to
        # say so there too, not only in a log line nobody quotes in a paper.
        return replace(
            report,
            extra={
                **report.extra,
                "parameter_uncertainty_absent_note": _NO_STATION_TO_TAKE_A_WIDTH_FROM,
            },
        )
    report = attach_a_linearized_width(
        report,
        cfg=phase_cfg,
        trial_ctx=trial_ctx,
        space=space,
        perturbation=float(uncertainty.perturbation),
    )
    if frozen and report.parameter_uncertainty:
        held = ", ".join(sorted({item.name for item in frozen}))
        note = (
            f"conditional on {held}, frozen by an earlier phase rather than recalibrated "
            "here: this width does not carry their uncertainty"
        )
        logger.info("Phase %s: width is %s", phase_name, note)
        report = replace(report, extra={**report.extra, "parameter_uncertainty_note": note})
    return report


def _phase_can_carry_a_linearized_width(phase_cfg: CalibrationConfig) -> bool:
    """Whether this phase scores an output a linearized width can be taken from.

    The question is whether a residual vector can exist here at all, and
    ``bool(phase_cfg.outputs)`` is not that question. The only registered
    protocol scores its steady stage on a ``support = "network"`` output, and
    ``CalibOutputNetwork`` carries no ``observes`` field - the loader refuses
    one. That phase holds an output, holds no station, and can never hold one:
    asking for a width there killed the whole staged run after the steady
    search had been paid for.

    So two levels, and they are not the same answer:

    - an output that names a station: a width can be taken, return True;
    - none names one, but one COULD: a document mistake, return True and let
      the call below fail loudly, which is what D231 asks for;
    - none can, because no output of this phase even carries the field: the
      shape of the phase, not a mistake in the file. Return False.

    A single-metric phase lands in the third case for a different reason:
    ``_phase_config`` empties its ``outputs`` whatever the rest of the file
    declares.
    """
    outputs = phase_cfg.outputs or {}
    if any(getattr(decl, "observes", None) is not None for decl in outputs.values()):
        return True
    return any(hasattr(decl, "observes") for decl in outputs.values())


def _require_result_for_dependents(
    decl: CalibPhaseDecl,
    report: CalibrationReport,
    remaining: Sequence[_PhasePlan],
) -> None:
    """Stop the chain when a phase froze nothing the phases after it need.

    A phase nobody builds on may fail harmlessly: it freezes nothing, says so,
    and the chain goes on. A phase a later one declares as its dependency is
    another matter. ``_require_dependency`` is satisfied because that phase
    ran, so the dependent would calibrate against the values the TOML declares
    instead of against what its dependency was meant to fix, and nothing in the
    result would say so.
    """
    if not decl.freeze_on_success or _settled(report):
        return
    dependents = [plan.decl.name for plan in remaining if plan.decl.depends_on == decl.name]
    if not dependents:
        return
    raise CalibrationError(
        f"phase {decl.name!r} freezes what {dependents} calibrate on top of, but "
        f"{_why_unsettled(report)}. Running {dependents} now would calibrate them "
        f"against the values the TOML declares. Make {decl.name!r} settle, then run "
        "the staged calibration again."
    )


# ---------------------------------------------------------------------------
# Phase selection
# ---------------------------------------------------------------------------


def _phases_to_run(
    cfg: CalibrationConfig,
    phase: str | None,
) -> list[tuple[int, CalibPhaseDecl]]:
    """Return the declared phases to run, in declaration order."""
    declared = cfg.phases or []
    if not declared:
        raise CalibrationError(
            "the calibration declares no [[calibration.phases]]; run it through "
            "run_calibration_cli instead."
        )
    ordered = list(enumerate(declared))
    if phase is None:
        return ordered
    selected = [item for item in ordered if item[1].name == phase]
    if not selected:
        raise CalibrationError(
            f"unknown phase {phase!r}; the calibration declares {[item.name for item in declared]}."
        )
    return selected


def _require_dependency(decl: CalibPhaseDecl, ran: set[str]) -> None:
    """Refuse a phase whose dependency neither ran here nor completed in the session.

    A dependent phase is written against the values its dependency freezes.
    Running it without them would not fail: it would calibrate against the
    baseline the TOML declares, which is a different calibration than the one
    asked for, and nothing in the result would say so. ``ran`` holds the phases
    solved in this invocation and, under ``--resume``, the ones read back.
    """
    if decl.depends_on is None or decl.depends_on in ran:
        return
    raise CalibrationError(
        f"phase {decl.name!r} depends on {decl.depends_on!r}, which did not run in this "
        f"invocation and did not complete in the session, so the values "
        f"{decl.depends_on!r} freezes are missing. Running {decl.name!r} alone would "
        "calibrate it against un-frozen parameters. Run the staged calibration without "
        "selecting a single phase, or with --resume on a session where it completed."
    )


# ---------------------------------------------------------------------------
# Reuse from a previous invocation
# ---------------------------------------------------------------------------


def _reused_phase_cost_block_fractions(
    phase_cfg: CalibrationConfig,
    persistence: CalibrationPersistence,
    phase: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return a reused phase's ``cost_block_fractions``, or why it has none.

    Same definition as the live path
    (:func:`hydromodpy.calibration.runners.cli_runner._phase_cost_block_fractions`),
    through the same functions, read from the journaled trials of the phase
    instead of an in-memory history.

    A phase with fewer than two declared blocks has nothing to report, same
    as the live path: returns ``(None, None)``. One with two or more whose
    journaled trials carry no usable ``<block>.total`` (journaled at
    ``persist_iteration_detail = "none"``) gets an explicit note instead of a
    fraction: the components are simply not on disk to read back.
    """
    blocks = [(str(block.name), float(block.weight)) for block in phase_cfg.objective_blocks or []]
    if len(blocks) < 2:
        return None, None
    rows = persistence.load_iterations(phase)
    finished = [
        row
        for row in rows
        if row.get("status") == "completed"
        and isinstance(row.get("cost"), (int, float))
        and math.isfinite(row["cost"])
    ]
    mean_result = mean_cost_block_fractions(blocks, (row.get("components") for row in finished))
    if mean_result is None:
        return None, (
            "reused from a previous run: its journaled trials carry no cost fraction "
            "to read back, so it is not recomputed here"
        )
    mean_fractions, n_trials = mean_result
    payload: dict[str, Any] = {"mean": mean_fractions, "mean_n_trials": n_trials}
    best_row = min(finished, key=lambda row: row["cost"])
    best_fractions = cost_block_fractions(best_row.get("components"), blocks)
    if best_fractions is not None:
        payload["best"] = best_fractions
    return payload, None


def _reuse_from_disk(
    *,
    persistence: CalibrationPersistence,
    decl: CalibPhaseDecl,
    declared: ParameterSpace,
    phase_cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    override_paths: dict[str, str],
    objective: str | None,
    project_root: Path,
) -> tuple[CalibrationReport, tuple[FrozenParameter, ...]] | None:
    """Return ``decl``'s result read back from the reopened session, or ``None``.

    ``None`` when the phase never completed in the session, or when its
    recorded ``params_hash`` cannot be reproduced under this invocation's own
    model, mesh and input files (:func:`~hydromodpy.calibration.runners.resume.fingerprint_matches`).
    Either way the caller solves the phase itself; this never runs anything.
    """
    stage = reusable_stage(persistence, decl.name)
    if stage is None:
        return None
    cache_context = build_cache_context(
        cfg=phase_cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=override_paths,
        objective_entrypoint=objective,
    )
    if not fingerprint_matches(stage, cache_context=cache_context):
        changed = differing_members(
            persistence.recorded_context(decl.name), context_fingerprints(cache_context)
        )
        logger.warning(
            "Phase %s completed in session %s, but its recorded fingerprint does not "
            "match this run (%s changed); solving it again instead of trusting a "
            "different problem's result.",
            decl.name,
            persistence.directory.name,
            ", ".join(changed) or "the context",
        )
        return None
    missing = [name for name in decl.parameters if name not in stage.parameters]
    if missing:
        logger.warning(
            "Phase %s of session %s carries no value for %s; solving it again.",
            decl.name,
            persistence.directory.name,
            missing,
        )
        return None
    froze = (
        tuple(
            FrozenParameter(parameter=declared[name], value=stage.parameters[name], phase=decl.name)
            for name in decl.parameters
        )
        if decl.freeze_on_success
        else ()
    )
    fractions, absent_note = _reused_phase_cost_block_fractions(phase_cfg, persistence, decl.name)
    extra: dict[str, Any] = {"reused_from_disk": True, "search_status": "completed"}
    if absent_note is not None:
        extra["cost_block_fractions_absent_note"] = absent_note
    pointer = persistence.best_pointer(persistence.held_trial(decl.name))
    reused = persistence.phase(decl.name)
    report = CalibrationReport(
        session_id=persistence.descriptor.session_id,
        method=phase_cfg.method,
        n_trials=stage.n_trials,
        best_cost=stage.best_cost,
        best_trial=stage.trial,
        duration_s=0.0,
        save_runs="none",
        promoted=0,
        best_parameters=dict(stage.parameters),
        best_cases={} if pointer is None else dict(pointer.cases),
        cost_block_fractions=fractions,
        workspace=project_root,
        session_dir=persistence.directory,
        cost_name=None if reused is None else reused.cost_name,
        cost_label=None if reused is None else reused.cost_label,
        windows={} if reused is None else dict(reused.windows),
        extra=extra,
    )
    return report, froze


def _frozen_by_the_session(
    cfg: CalibrationConfig,
    persistence: CalibrationPersistence,
    declared: ParameterSpace,
    plans: Sequence[_PhasePlan],
) -> list[FrozenParameter]:
    """Return what the completed phases a run does not select froze, read from the session.

    ``--phase P`` runs one phase on top of the session: the values the earlier
    phases passed on come from their best trials in the journal, in declaration
    order, exactly as if they had run in this invocation.
    """
    selected = {plan.decl.name for plan in plans}
    completed = completed_phases(persistence)
    frozen: list[FrozenParameter] = []
    for decl in cfg.phases or ():
        if decl.name in selected or decl.name not in completed or not decl.freeze_on_success:
            continue
        values = best_parameters_of(persistence, decl.name)
        frozen.extend(
            FrozenParameter(parameter=declared[name], value=values[name], phase=decl.name)
            for name in decl.parameters
            if name in values
        )
    return frozen


@dataclass(frozen=True, slots=True)
class PhaseReplay:
    """The model one phase of a session scored its trials under, prepared again.

    ``config`` is the configuration of the phase, the one the params hash of
    its trials reads; ``space`` the parameters it moved; ``trial_ctx`` the
    prepared pipeline, with the phase overrides and the values earlier phases
    passed on written into its baseline.
    """

    config: CalibrationConfig
    space: ParameterSpace
    trial_ctx: TrialContext


def replay_phase(
    cfg: CalibrationConfig,
    raw: Mapping[str, Any],
    cfg_path: Path,
    phase: str,
    frozen: Mapping[str, FrozenValue],
) -> PhaseReplay:
    """Prepare the trials of ``phase`` the way the staged search prepared them.

    *frozen* is what the phase descriptor of the session recorded, the values
    the phase held fixed (:func:`_frozen_payload`). The steps are those of
    :func:`run_staged_calibration`: the phase configuration and its overrides,
    the trial pipeline, then the held values written into its baseline. A
    trial replayed on it reproduces its ``params_hash``.
    """
    selected = [(index, decl) for index, decl in enumerate(cfg.phases or ()) if decl.name == phase]
    if not selected:
        raise CalibrationError(f"the calibration declares no phase {phase!r}.")
    plan = _phase_plans(cfg, selected, raw)[0]
    declared = space_from_config(cfg)
    held = [
        FrozenParameter(parameter=declared[name], value=entry.value, phase=entry.from_phase)
        for name, entry in frozen.items()
        if name in declared.names
    ]
    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=_injected_paths(plan.config, held),
        config_overrides=dict(plan.overrides),
        parameter_space=plan.space,
    )
    _freeze_into_baseline(trial_ctx, held)
    return PhaseReplay(config=plan.config, space=plan.space, trial_ctx=trial_ctx)


def _frozen_payload(held: Sequence[FrozenParameter], case_id: str) -> dict[str, FrozenValue]:
    """Return the frozen values of a phase as its descriptor writes them."""
    return {
        item.name: FrozenValue(
            value=float(item.value),
            targets={case_id: item.path} if item.path else {},
            mode=item.parameter.mode,
            from_phase=item.phase,
        )
        for item in held
    }


# ---------------------------------------------------------------------------
# Comparisons: what each block, or the single-metric route, compares with what
# ---------------------------------------------------------------------------


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
    ``hmp config check`` can show it for a plain calibration's one search, which
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


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@in_run_scratch(
    lambda config_path, **kw: project_root_for(Path(config_path), kw.get("workspace")),
    lambda config_path, **_kw: Path(config_path).stem,
    check=lambda *_a, **kw: refuse_an_objective_that_is_not_an_entry_point(kw.get("objective")),
)
def run_staged_calibration(
    config_path: Path | str,
    *,
    phase: str | None = None,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str | None = None,
    metric_fn: TrialMetricFn | None = None,
    resume: bool = False,
) -> CalibrationReport:
    """Run the phases of ``config_path`` one after the other, in one session.

    Parameters
    ----------
    config_path
        Path to a TOML declaring ``[calibration]`` with a ``phases`` table.
    phase
        Run only the phase of that name. It still needs the values its
        dependency freezes: the dependency must have completed in the
        session reopened by ``resume``, or the phase is refused.
    objective
        Escape hatch ``"module.path:callable"`` selecting the metric
        extractor, forwarded to every phase.
    workspace
        Override the project root, otherwise resolved from the TOML.
    project
        Project name written in the outcome of the session. Unset, the
        name of the project root folder.
    metric_fn
        Programmatic override for the metric extractor.
    resume
        Reopen the latest session of the case. A phase that completed there
        with the same fingerprint is read back instead of solved; the cut
        phase is solved again with its trials preloading the cache.

    ``objective`` is refused by the decorator, before the reuse branch and not
    inside the search: a run that reuses every phase from disk never reaches the
    consumer, and the value travels into the reuse fingerprint either way.
    """
    cfg_path, project_root, cfg, raw, case = load_calibration_document(config_path, workspace)
    if not evaluation_registry.needs_prepared_model(cfg.evaluator):
        # A staged calibration freezes a phase's result into the configuration
        # the next phase runs with, and that configuration is the pipeline's.
        # An evaluator that reads none of it would run every phase on the same
        # unfrozen parameters and report a protocol it did not follow -- silently,
        # because each phase would still return a number.
        raise CalibrationError(
            f"calibration.evaluator names {cfg.evaluator!r}, which runs no HydroModPy model, "
            "and this document declares phases. A staged protocol passes each phase's result "
            "to the next by freezing it into the model configuration, which that evaluator "
            "never reads. Run the phases as separate single-phase documents, or name an "
            "evaluator that runs the pipeline."
        )
    plans = _phase_plans(cfg, _phases_to_run(cfg, phase), raw)
    declared = space_from_config(cfg)
    promotion_name_check(case)
    reopen = resume or phase is not None
    persistence: CalibrationPersistence | None = None
    frozen: list[FrozenParameter] = []
    reopening = False
    if reopen:
        existing = latest_session_dir(project_root, case)
        if existing is not None:
            # Reopened at the first phase that writes, after the checks that may
            # refuse it, so that a refusal leaves the session as it was.
            persistence = CalibrationPersistence(existing)
            reopening = True
            frozen.extend(_frozen_by_the_session(cfg, persistence, declared, plans))
    last_decl = plans[-1].decl
    runs: list[PhaseRun] = []
    restart_spreads: list[RestartSpread] = []
    reused_from_disk: list[str] = []
    ran: set[str] = set()
    solved_reports: list[CalibrationReport] = []
    trial_ctx: TrialContext | None = None
    scope = SessionScope(
        cfg=cfg,
        project_root=project_root,
        persistence=None if reopening else persistence,
        phase=last_decl.name,
    )
    promotion_extra: dict[str, Any] = {}
    with closing_session(scope):
        for position, plan in enumerate(plans):
            index, decl, phase_cfg, space = plan.index, plan.decl, plan.config, plan.space
            scope.phase = decl.name
            if persistence is not None:
                ran.update(completed_phases(persistence))
            _require_dependency(decl, ran)
            try:
                trial_ctx = prepare_trials(
                    cfg_path,
                    override_paths=_injected_paths(phase_cfg, frozen),
                    config_overrides=dict(plan.overrides),
                    parameter_space=space,
                )
            except ConfigValidationError as exc:
                raise ConfigValidationError(
                    f"phase {decl.name!r} cannot prepare its trials: {exc}"
                ) from exc
            check_the_prepared_model(phase_cfg, trial_ctx, space)
            scope.trial_ctx = trial_ctx
            if persistence is None:
                persistence, _ = open_calibration_session(
                    project_root,
                    case,
                    resume=False,
                    raw=raw,
                    cfg=cfg,
                    space=declared,
                    trial_ctx=trial_ctx,
                    project=project,
                )
                scope.persistence = persistence

            held = _held(frozen, space)
            reopened_values = _reopened(frozen, space)
            # Before anything reads this baseline, including the fingerprint that
            # decides whether a completed phase may be reused. The hash recorded on
            # disk for this phase was computed with the upstream freezes baked in, so
            # asking the question without them can only ever answer no.
            _freeze_into_baseline(trial_ctx, held)

            disk_result: tuple[CalibrationReport, tuple[FrozenParameter, ...]] | None = None
            if reopen:
                disk_result = _reuse_from_disk(
                    persistence=persistence,
                    decl=decl,
                    declared=declared,
                    phase_cfg=phase_cfg,
                    trial_ctx=trial_ctx,
                    space=space,
                    override_paths=resolve_override_paths(phase_cfg),
                    objective=objective,
                    project_root=project_root,
                )

            if reopening:
                if disk_result is None:
                    refuse_a_phase_another_cost_scored(
                        persistence,
                        decl.name,
                        build_cache_context(
                            cfg=phase_cfg,
                            trial_ctx=trial_ctx,
                            space=space,
                            override_paths=resolve_override_paths(phase_cfg),
                            objective_entrypoint=objective,
                        ),
                    )
                persistence.resume_session()
                persistence.start_pulse()
                scope.persistence = persistence
                reopening = False

            if disk_result is not None:
                report, froze = disk_result
                status: SessionStatus = "completed"
                reused = persistence.phase(decl.name)
                stop_note = reused.stop_note if froze and reused is not None else None
                reused_from_disk.append(decl.name)
                logger.info(
                    "Phase %s already completed in session %s; reusing its best trial "
                    "instead of solving it again.",
                    decl.name,
                    persistence.directory.name,
                )
                if getattr(phase_cfg.uncertainty, "method", None) == "linearized":
                    if _phase_can_carry_a_linearized_width(phase_cfg):
                        note = (
                            "not attached: this phase was reused from the reopened session "
                            "rather than solved, and building a linearized width perturbs "
                            "and reruns the model, the exact cost the reuse avoids"
                        )
                    else:
                        # Reuse is not why this one is absent: a phase whose outputs
                        # cannot name a station carries no width whether it is reused
                        # or solved.
                        note = _NO_STATION_TO_TAKE_A_WIDTH_FROM
                    logger.info("Phase %s: linearized width is %s", decl.name, note)
                    report = replace(
                        report, extra={**report.extra, "parameter_uncertainty_absent_note": note}
                    )
            else:
                restart_of = persistence.phase(decl.name)
                context = PhaseContext(
                    decl.name,
                    index,
                    restart=0 if restart_of is None else restart_of.restarts + 1,
                )
                persistence.start_phase(
                    context,
                    frozen=_frozen_payload(held, persistence.case_id),
                    cost_name=session_cost_name(cfg, decl),
                    cost_label=cost_metric_label(cfg, decl),
                    windows=search_windows(cfg, raw, phase=decl),
                )
                logger.info(
                    "Calibration phase %d/%d %s | method=%s parameters=%s",
                    index + 1,
                    len(cfg.phases or []),
                    decl.name,
                    phase_cfg.method,
                    list(decl.parameters),
                )
                passed_start = _passed_start(decl.name, phase_cfg.method, space, reopened_values)
                keep_trial_solves(phase_cfg, trial_ctx)
                report, spread = run_one_search(
                    phase_cfg,
                    trial_ctx,
                    persistence=persistence,
                    space=space,
                    project_root=project_root,
                    cfg_path=cfg_path,
                    metric_fn=metric_fn,
                    objective=objective,
                    phase=context,
                    passed_start=passed_start,
                    interval_width=plan.width,
                    balanced=decl.balanced_evaluation,
                )
                restart_spreads.extend(spread)
                report = _attach_linearized_width(
                    report,
                    phase_cfg=phase_cfg,
                    phase_name=decl.name,
                    trial_ctx=trial_ctx,
                    space=space,
                    frozen=held,
                )
                froze = _frozen_by(decl, report, declared)
                stop_note = report.extra.get("root_outside_bounds") or (
                    FROZE_BUDGET_ONLY if froze and _froze_budget_only(report) else None
                )
                status = str(report.extra.get("search_status", "completed"))
                search = report.extra.get("search") or {}
                # What the search answered with is what the phase passes on.
                pointer, scored = answered_best(persistence, report, decl.name)
                closed = persistence.finish_phase(
                    decl.name,
                    status=status,
                    best=pointer,
                    scored=scored,
                    stop_state=search.get("stop_state"),
                    stopping_rule=search.get("stopping_rule"),
                    stop_note=stop_note,
                    widths=parameter_widths(report, spread),
                )
                report = replace(
                    report,
                    status=status,
                    best_cases={} if pointer is None else dict(pointer.cases),
                    windows=dict(closed.windows),
                )
                solved_reports.append(report)
                if cfg.promote_phases and position < len(plans) - 1:
                    promote_phase_best(
                        trial_ctx=trial_ctx,
                        persistence=persistence,
                        phase=decl.name,
                        override_paths=resolve_override_paths(phase_cfg),
                        outputs=phase_cfg.outputs,
                    )
                if position < len(plans) - 1:
                    release_trial_solves(trial_ctx)
                    release_session_scratch(trial_ctx)

            _require_result_for_dependents(decl, report, plans[position + 1 :])
            frozen.extend(froze)
            runs.append(
                PhaseRun(
                    name=decl.name,
                    index=index,
                    session_id=persistence.descriptor.session_id,
                    report=report,
                    frozen=froze,
                    reopened=reopened_values,
                    status=status,
                    stop_note=stop_note,
                )
            )
            ran.add(decl.name)

        steady_window = _steady_window_summary(cfg, runs, raw)
        methods = (
            _methods_paragraph_for(
                cfg,
                runs,
                frozen,
                raw,
                backend=_backend_name(raw),
                steady_window=steady_window,
                geographic=_geographic_choices(raw),
            )
            if cfg.protocol is not None
            else None
        )
        methods_path = (
            write_methods(persistence.directory, methods)
            if methods is not None and persistence is not None
            else None
        )
        last_report = runs[-1].report
        session_status = session_status_of(solved_reports) if solved_reports else "completed"
        final = promote_and_close(
            cfg=cfg,
            trial_ctx=trial_ctx,
            persistence=persistence,
            project_root=project_root,
            report=last_report,
            phase=last_decl.name,
            status=session_status,
            stop_note="; ".join(
                f"phase {run.name} {run.stop_note}" for run in runs if run.stop_note
            )
            or None,
            # A later phase wins for a value two phases calibrated.
            widths=persistence.phase_widths(),
        )
        runs[-1] = replace(runs[-1], report=final)
        if final.extra.get("promotion_failures"):
            promotion_extra["promotion_failures"] = list(final.extra["promotion_failures"])

    descriptor = persistence.descriptor
    return replace(
        final,
        method=descriptor.method,
        n_trials=sum(run.report.n_trials for run in runs),
        duration_s=sum(run.report.duration_s for run in runs),
        save_runs=cfg.save_runs,
        best_parameters=(None if descriptor.best is None else dict(descriptor.best.parameters)),
        phases=tuple(runs),
        frozen=tuple(frozen),
        extra=promotion_extra,
        protocol=(
            protocol_record(cfg.protocol.name, cfg.protocol) if cfg.protocol is not None else None
        ),
        methods_paragraph=methods,
        methods_path=methods_path,
        restart_spreads=tuple(restart_spreads),
        reused_from_disk=tuple(reused_from_disk),
        steady_window=steady_window,
    )


def _backend_name(document: Mapping[str, Any]) -> str:
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
    declared = (
        solver_name_of_backend(solver.get("backend")) if isinstance(solver, Mapping) else None
    )
    return declared or SolverConfig().backend_name


_GEOGRAPHIC_DEVIATIONS = ("dem_correc_type",)
"""Keys a protocol departs on that live under ``[geographic]``, not on an output."""


def _geographic_choices(document: Mapping[str, Any]) -> dict[str, object]:
    """Return the ``[geographic]`` values the file wrote on a key the protocol departs on.

    Read from the raw document, as the backend is: a key present there is one
    the file set, after ``base_config`` and the legacy migrations. A key left
    unset takes the model's default, which the deviation table already
    describes, so it stays out of the Methods paragraph.

    A ``capped_breach`` is not reproducible without its limits, so the value
    names them, defaults included.
    """
    geographic = document.get("geographic")
    if not isinstance(geographic, Mapping):
        return {}
    chosen = {key: geographic[key] for key in _GEOGRAPHIC_DEVIATIONS if key in geographic}
    if chosen.get("dem_correc_type") == "capped_breach":
        from hydromodpy.spatial.geographic.capped_breach_config import CappedBreachConfig

        section = geographic.get("capped_breach")
        limits = CappedBreachConfig.model_validate(dict(section) if section else {})
        chosen["dem_correc_type"] = (
            f"capped_breach (max_depth = {float(limits.max_depth):g} m, "
            f"max_distance = {float(limits.max_distance):g} m)"
        )
    return chosen


def _steady_window_summary(
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


def _methods_paragraph_for(
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
    the protocol departs on (:func:`_geographic_choices`). A network output
    never declares those keys, so the two sources cannot disagree.
    """
    from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

    if cfg.protocol is None:
        return None
    completed = [run.name for run in runs if _settled(run.report)]
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
        if not _settled(run.report)
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


__all__ = [
    "PhaseReplay",
    "objective_comparison_table",
    "phase_summaries",
    "replay_phase",
    "run_staged_calibration",
]
