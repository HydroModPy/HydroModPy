"""Calibration run in phases: each stage calibrates, then freezes.

A staged calibration runs the phases of ``[[calibration.phases]]`` in
declaration order. Each phase is an ordinary mono-phase calibration: it gets
its own configuration, its own optimizer, its own session, and goes through
:func:`hydromodpy.calibration.runners.cli_runner.run_calibration_core` like
any other. What staging adds is what happens between two phases.

Freezing
--------
A phase that declares ``freeze_on_success`` and converges hands the
parameters it calibrated to the phases after it, as fixed values. A frozen
parameter leaves the search: it is written once into the baseline
configuration every trial of the next phase forks from, and its declaration
is dropped from that phase's parameter space. Keeping it in the space with
equal bounds would make a grid sampler spend points on a degenerate axis and
would break the one-dimensional guard of the bisection adapter.

Chaining
--------
The phases write one session each. Phase 0 is the root of the chain and has
no parent; every later phase records the previous one as its parent and phase
0 as its root. The four values travel through :class:`SessionChain` into
``session.json``, so ``hmp catalog reindex`` gives the chain back.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.protocols import (
    protocol_options_away_from_the_recipe,
    protocol_record,
)
from hydromodpy.calibration.runners.cli_runner import (
    attach_a_linearized_width,
    load_toml_calibration,
    run_calibration_core,
)
from hydromodpy.calibration.runners.restarts import RestartSpread, run_restarts
from hydromodpy.calibration.runners.resume import fingerprint_matches, reusable_stage
from hydromodpy.calibration.runners.state import (
    CalibrationStoreFactory,
    SessionChain,
    build_cache_context,
    default_store_factory,
    space_from_config,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials
from hydromodpy.core.exceptions import CalibrationError, ConfigValidationError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenParameter:
    """One parameter a phase calibrated and held fixed for the phases after it.

    The declaration is the one the parent configuration carries, so the dotted
    path and the mode (``replace`` / ``scale``) are honoured exactly as during
    the phase that calibrated the value.
    """

    parameter: CalibParameter
    value: float
    phase: str

    @property
    def name(self) -> str:
        """Calibration name of the frozen parameter."""
        return self.parameter.name

    @property
    def path(self) -> str | None:
        """Dotted path in the configuration the value is written to."""
        return self.parameter.effective_path

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the frozen value."""
        return {
            "name": self.name,
            "path": self.path,
            "value": float(self.value),
            "mode": self.parameter.mode,
            "phase": self.phase,
        }


@dataclass(frozen=True, slots=True)
class PhaseRun:
    """One phase of a staged calibration: its session, its report, its freeze."""

    name: str
    index: int
    session_id: str
    root_session_id: str
    parent_session_id: str | None
    report: CalibrationReport
    frozen: tuple[FrozenParameter, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the phase, report included."""
        return {
            "phase": self.name,
            "index": self.index,
            "session_id": self.session_id,
            "root_session_id": self.root_session_id,
            "parent_session_id": self.parent_session_id,
            "frozen": [item.to_dict() for item in self.frozen],
            "report": self.report.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class StagedCalibrationReport:
    """Outcome of a calibration run in phases.

    ``phases`` keeps the runs in the order they ran and ``frozen`` gathers,
    in the same order, every value a converged phase declared frozen, with
    the path it is written to.
    """

    phases: tuple[PhaseRun, ...]
    frozen: tuple[FrozenParameter, ...]
    root_session_id: str
    protocol: dict[str, Any] | None = None
    """The published method that wrote these stages, when one did."""

    methods_paragraph: str | None = None
    """The prose this run writes about itself, conditioned on the stages that
    completed. It is the only object by which someone who did not produce the
    number can know what it rests on without reading Python."""

    restart_spreads: tuple[RestartSpread, ...] = ()
    """Where the restarts of each phase landed, when the file asked for restarts.

    The calibrated value is untouched: it is the best of them. This says how far
    apart the others finished, which is the one thing a single search cannot
    report about itself."""

    reused_from_disk: tuple[str, ...] = ()
    """Names of the phases read back from a previous session instead of solved.

    Only non-empty when ``[calibration] reuse_completed_phases`` was on and a
    ``resume_root_session_id`` was given: what it reused is a session whose
    fingerprint matched this run's own model, mesh and input files."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary for the CLI."""
        summary: dict[str, Any] = {
            "root_session_id": self.root_session_id,
            "phases": [phase.to_dict() for phase in self.phases],
            "frozen": [item.to_dict() for item in self.frozen],
        }
        if self.protocol is not None:
            summary["protocol"] = self.protocol
        if self.methods_paragraph is not None:
            summary["methods_paragraph"] = self.methods_paragraph
        if self.reused_from_disk:
            summary["reused_from_disk"] = list(self.reused_from_disk)
        if self.restart_spreads:
            summary["restart_spreads"] = [item.to_dict() for item in self.restart_spreads]
        return summary


# ---------------------------------------------------------------------------
# Phase configuration
# ---------------------------------------------------------------------------


def _seed_of(cfg: CalibrationConfig) -> int:
    return 0 if cfg.seed is None else int(cfg.seed)


def _declared_restarts(cfg: CalibrationConfig) -> int | None:
    """Return how many times each phase repeats its search, or None for one pass."""
    uncertainty = getattr(cfg, "uncertainty", None)
    if uncertainty is None or getattr(uncertainty, "method", None) != "multistart":
        return None
    return int(uncertainty.restarts)


def _phase_config(cfg: CalibrationConfig, decl: CalibPhaseDecl) -> CalibrationConfig:
    """Return the mono-phase configuration one phase runs under.

    The phase carries its own search (method, budget, parameters) and selects
    by name from what the calibration declares. An empty selection of outputs
    means the ones its blocks read, and an empty selection of blocks means every
    declared one. A phase declaring its own ``variable`` or ``objective`` takes
    the single-metric route instead, and inherits neither. ``phases`` is cleared
    so the sub-run is an ordinary calibration.

    A phase used to inherit every declared output whatever it scored. A
    two-stage file naming a network output for its steady stage and a discharge
    output for its transient one therefore handed each stage the output of the
    other, to be extracted from every trial and to weigh nothing. It was not
    only waste: a stage whose criteria cannot read an inherited output is
    refused, so that file did not run at all.
    """
    payload = cfg.model_dump()
    payload["method"] = decl.method
    payload["max_iter"] = decl.max_iter
    payload["tolerance"] = decl.tolerance
    payload["batch_size"] = decl.batch_size
    payload["parallel"] = decl.parallel
    payload["optimizer_kwargs"] = dict(decl.optimizer_kwargs)
    if decl.variable is not None:
        payload["variable"] = decl.variable
    if decl.objective is not None:
        payload["objective"] = decl.objective
    if decl.observed_station_id is not None:
        payload["observed_station_id"] = decl.observed_station_id
    if decl.scoring_window is not None:
        payload["scoring_window"] = decl.scoring_window.model_dump()
    payload["parameters"] = {name: payload["parameters"][name] for name in decl.parameters}
    if decl.is_single_metric:
        # The extractor prefers blocks over the variable whenever both are
        # present, so a phase inheriting the blocks of another one would be
        # scored on that other criterion without saying so.
        payload["outputs"] = {}
        payload["objective_blocks"] = []
    else:
        if decl.objective_blocks:
            selected = set(decl.objective_blocks)
            payload["objective_blocks"] = [
                block for block in payload["objective_blocks"] if block["name"] in selected
            ]
        if decl.outputs:
            payload["outputs"] = {name: payload["outputs"][name] for name in decl.outputs}
        elif decl.objective_blocks:
            read = {name for block in payload["objective_blocks"] for name in block["uses_outputs"]}
            payload["outputs"] = {
                name: value for name, value in payload["outputs"].items() if name in read
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
    """One selected phase, with the calibration and the space it runs under."""

    index: int
    decl: CalibPhaseDecl
    config: CalibrationConfig
    space: ParameterSpace


def _phase_plans(
    cfg: CalibrationConfig,
    selected: Sequence[tuple[int, CalibPhaseDecl]],
) -> list[_PhasePlan]:
    """Build every selected phase before the first one runs.

    ``_check_phases`` validates the phase table against the calibration it
    narrows, not against the configuration each phase ends up with, so a phase
    that cannot describe a runnable calibration of its own is only found when
    its turn comes: after the phases before it have spent their whole solve
    budget. Building them all here moves that refusal before the first solve,
    and the loop then runs what was built instead of building it again.
    """
    plans: list[_PhasePlan] = []
    for index, decl in selected:
        phase_cfg = _phase_config(cfg, decl)
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
        plans.append(_PhasePlan(index=index, decl=decl, config=phase_cfg, space=space))
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


def _freeze_into_baseline(trial_ctx: TrialContext, frozen: list[FrozenParameter]) -> None:
    """Write the frozen values into the baseline the phase forks from.

    ``TrialContext.fork`` starts every trial from a deep copy of ``base_cfg``
    and then writes the sampled values in, so a value written here reaches
    every trial of the phase without ever entering its search. The write goes
    through the same helper the fork uses, on a baseline freshly loaded from
    the TOML, so ``mode="scale"`` multiplies the declared value once and
    exactly as the phase that calibrated it did.
    """
    for item in frozen:
        apply_parameter_to_config(trial_ctx.base_cfg, item.parameter, item.value)


def _converged(report: CalibrationReport) -> bool:
    """Whether a phase produced a candidate the next phases can build on.

    Convergence, not quality: a coarse agreement still returns a number. What
    disqualifies a phase is having no best candidate at all, or a best cost
    that is the failed-evaluation sentinel.
    """
    if report.best_parameters is None or report.best_objective is None:
        return False
    return math.isfinite(report.best_objective) and report.best_objective < FAILED_EVAL_COST


def _frozen_by(
    decl: CalibPhaseDecl,
    report: CalibrationReport,
    declared: ParameterSpace,
) -> tuple[FrozenParameter, ...]:
    """Return what this phase hands to the phases that depend on it."""
    if not decl.freeze_on_success:
        return ()
    if not _converged(report):
        logger.warning(
            "Phase %s did not converge; its parameters stay free for the next phases.",
            decl.name,
        )
        return ()
    values = report.best_parameters or {}
    missing = [name for name in decl.parameters if name not in values]
    if missing:
        raise CalibrationError(
            f"phase {decl.name!r} converged but its best candidate carries no value for "
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
    cfg: CalibrationConfig,
    phase_cfg: CalibrationConfig,
    phase_name: str,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    frozen: Sequence[FrozenParameter],
) -> CalibrationReport:
    """Attach a linearized width to one phase's report, when the document asks for one.

    ``uncertainty.method`` is declared once for the whole document, so every
    phase shares it (D234 in the campaign decisions): the width is built at the
    end of each phase, from the parameters and the outputs THAT PHASE scored --
    ``phase_cfg``, not ``cfg``.

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
    uncertainty = getattr(cfg, "uncertainty", None)
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
    if not decl.freeze_on_success or _converged(report):
        return
    dependents = [plan.decl.name for plan in remaining if plan.decl.depends_on == decl.name]
    if not dependents:
        return
    raise CalibrationError(
        f"phase {decl.name!r} freezes what {dependents} calibrate on top of, but its "
        f"session {report.session_id} produced no result over {report.n_iterations} "
        "trial(s): no best candidate, or a best cost at the failed-evaluation "
        f"sentinel. Running {dependents} now would calibrate them against the values "
        f"the TOML declares. Make {decl.name!r} produce a candidate, then run the "
        "staged calibration again."
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
    """Refuse a phase whose dependency did not run in this invocation.

    A dependent phase is written against the values its dependency freezes.
    Running it without them would not fail: it would calibrate against the
    baseline the TOML declares, which is a different calibration than the one
    asked for, and nothing in the result would say so.
    """
    if decl.depends_on is None or decl.depends_on in ran:
        return
    raise CalibrationError(
        f"phase {decl.name!r} depends on {decl.depends_on!r}, which did not run in this "
        f"invocation, so the values {decl.depends_on!r} freezes are missing. Running "
        f"{decl.name!r} alone would calibrate it against un-frozen parameters. Run the "
        "staged calibration without selecting a single phase."
    )


# ---------------------------------------------------------------------------
# Reuse from a previous invocation
# ---------------------------------------------------------------------------


def _reuse_from_disk(
    *,
    resume_root_session_id: str,
    decl: CalibPhaseDecl,
    declared: ParameterSpace,
    phase_cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    override_paths: dict[str, str],
    objective: str | None,
    workspace: Path,
    store_factory: CalibrationStoreFactory | None,
) -> tuple[CalibrationReport, tuple[FrozenParameter, ...]] | None:
    """Return ``decl``'s result read from ``resume_root_session_id``'s chain, or ``None``.

    ``None`` when the phase never completed in that chain, or when its recorded
    ``params_hash`` cannot be reproduced under this invocation's own model, mesh
    and input files (:func:`hydromodpy.calibration.runners.resume.fingerprint_matches`).
    Either way the caller solves the phase itself; this never runs anything.
    """
    from hydromodpy.calibration.report import CalibrationReport

    factory = store_factory or default_store_factory
    catalog = factory(workspace, phase_cfg.persistence)
    stage = reusable_stage(catalog, resume_root_session_id, decl.name)
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
        logger.warning(
            "Phase %s has a completed session %s in the resumed chain %s, but its "
            "recorded fingerprint does not match this run's model, mesh or input "
            "files; solving it again instead of trusting a different problem's result.",
            decl.name,
            stage.session_id,
            resume_root_session_id,
        )
        return None
    missing = [name for name in decl.parameters if name not in stage.parameters]
    if missing:
        logger.warning(
            "Phase %s's session %s in the resumed chain carries no value for %s; solving it again.",
            decl.name,
            stage.session_id,
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
    report = CalibrationReport(
        session_id=stage.session_id,
        method=phase_cfg.method,
        n_iterations=stage.n_iterations,
        best_objective=stage.best_objective,
        best_sim_id=None,
        duration_s=0.0,
        save_runs="none",
        promoted=0,
        best_parameters=dict(stage.parameters),
        workspace=workspace,
        extra={"reused_from_disk": True, "source_root_session_id": resume_root_session_id},
    )
    return report, froze


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_staged_calibration(
    config_path: Path | str,
    *,
    phase: str | None = None,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    store_factory: CalibrationStoreFactory | None = None,
    return_report: bool = True,
    resume_root_session_id: str | None = None,
) -> StagedCalibrationReport | dict[str, Any]:
    """Run the phases of ``config_path`` one after the other.

    Parameters
    ----------
    config_path
        Path to a TOML declaring ``[calibration]`` with a ``phases`` table.
    phase
        Run only the phase of that name. It still needs the values its
        dependency freezes, so a phase whose dependency did not run in the
        same invocation is refused.
    objective
        Escape hatch ``"module.path:callable"`` selecting the metric
        extractor, forwarded to every phase.
    workspace
        Override the project catalog root, otherwise resolved from the TOML.
    project
        Project label written to ``calibration_sessions.project``.
    metric_fn
        Programmatic override for the metric extractor.
    store_factory
        Override for the calibration store, forwarded to every phase.
    return_report
        When True (the default), return the structured
        :class:`StagedCalibrationReport`; when False, its ``to_dict()``
        payload. Same choice as ``run_calibration_cli``, opposite default:
        every caller of the staged runner asks the report for its summary.
    resume_root_session_id
        Root session id of a previous invocation of this same staged
        calibration. A fresh call always starts its own chain, so without this
        there is nothing to resume against: it is what tells this invocation
        which chain's completed phases it may read back. Only has an effect
        together with ``[calibration] reuse_completed_phases = true``; every
        phase is still solved when either is missing.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = load_toml_calibration(cfg_path)
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
    plans = _phase_plans(cfg, _phases_to_run(cfg, phase))
    declared = space_from_config(cfg)

    frozen: list[FrozenParameter] = []
    runs: list[PhaseRun] = []
    restart_spreads: list[RestartSpread] = []
    reused_from_disk: list[str] = []
    ran: set[str] = set()
    parent_session_id: str | None = None
    root_session_id: str | None = resume_root_session_id

    for position, plan in enumerate(plans):
        index, decl, phase_cfg, space = plan.index, plan.decl, plan.config, plan.space
        _require_dependency(decl, ran)
        try:
            trial_ctx = prepare_trials(
                cfg_path,
                override_paths=_injected_paths(phase_cfg, frozen),
                config_overrides=dict(decl.overrides),
                parameter_space=space,
            )
        except ConfigValidationError as exc:
            raise ConfigValidationError(
                f"phase {decl.name!r} cannot prepare its trials: {exc}"
            ) from exc

        if workspace is not None:
            ws_root = Path(workspace).expanduser().resolve()
        else:
            ws_root = trial_ctx.workspace

        # Before anything reads this baseline, including the fingerprint that
        # decides whether a completed phase may be reused. The hash recorded on
        # disk for this phase was computed with the upstream freezes baked in, so
        # asking the question without them can only ever answer no.
        # Before anything reads this baseline, including the fingerprint that
        # decides whether a completed phase may be reused. The hash recorded on
        # disk for this phase was computed with the upstream freezes baked in, so
        # asking the question without them can only ever answer no.
        _freeze_into_baseline(trial_ctx, frozen)

        disk_result: tuple[CalibrationReport, tuple[FrozenParameter, ...]] | None = None
        if cfg.reuse_completed_phases and resume_root_session_id is not None:
            disk_result = _reuse_from_disk(
                resume_root_session_id=resume_root_session_id,
                decl=decl,
                declared=declared,
                phase_cfg=phase_cfg,
                trial_ctx=trial_ctx,
                space=space,
                override_paths=resolve_override_paths(phase_cfg),
                objective=objective,
                workspace=ws_root,
                store_factory=store_factory,
            )

        if disk_result is not None:
            report, froze = disk_result
            session_id = report.session_id
            if root_session_id is None:
                root_session_id = session_id
            reused_from_disk.append(decl.name)
            logger.info(
                "Phase %s already completed as session %s; reusing its best trial "
                "instead of solving it again (reuse_completed_phases).",
                decl.name,
                session_id,
            )
            if getattr(getattr(cfg, "uncertainty", None), "method", None) == "linearized":
                if _phase_can_carry_a_linearized_width(phase_cfg):
                    note = (
                        "not attached: this phase was reused from a previous run "
                        "(reuse_completed_phases) rather than solved, and building a "
                        "linearized width perturbs and reruns the model -- the exact "
                        "cost this reuse was written to avoid"
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
            session_id = uuid.uuid4().hex
            if root_session_id is None:
                root_session_id = session_id
            chain = SessionChain(
                session_id=session_id,
                root_session_id=root_session_id,
                phase_name=decl.name,
                phase_index=index,
                parent_session_id=parent_session_id,
            )

            logger.info(
                "Calibration phase %d/%d %s | method=%s parameters=%s",
                index + 1,
                len(cfg.phases or []),
                decl.name,
                decl.method,
                list(decl.parameters),
            )

            def _one_search(
                restart_seed: int,
                start_at,
                _cfg=phase_cfg,
                _chain=chain,
                _ctx=trial_ctx,
                _space=space,
                _ws=ws_root,
            ):
                return run_calibration_core(
                    _cfg
                    if restart_seed == _seed_of(_cfg)
                    else _cfg.model_copy(update={"seed": restart_seed}),
                    _ctx,
                    workspace=_ws,
                    space=_space,
                    project_label=project,
                    cfg_path=cfg_path,
                    metric_fn=metric_fn,
                    objective=objective,
                    store_factory=store_factory,
                    chain=_chain,
                    start_at=start_at,
                )

            restarts = _declared_restarts(cfg)
            if restarts is None:
                report = _one_search(_seed_of(phase_cfg), None)
                spread: tuple = ()
            else:
                logger.info(
                    "Phase %s runs %d restarts: the answer is the best of them, the spread "
                    "is reported beside it, and each restart is a full search.",
                    decl.name,
                    restarts,
                )
                report, spread = run_restarts(
                    _one_search,
                    method=phase_cfg.method,
                    space=space,
                    restarts=restarts,
                    seed=phase_cfg.seed,
                )
            restart_spreads.extend(spread)
            report = _attach_linearized_width(
                report,
                cfg=cfg,
                phase_cfg=phase_cfg,
                phase_name=decl.name,
                trial_ctx=trial_ctx,
                space=space,
                frozen=frozen,
            )
            froze = _frozen_by(decl, report, declared)

        _require_result_for_dependents(decl, report, plans[position + 1 :])
        frozen.extend(froze)
        runs.append(
            PhaseRun(
                name=decl.name,
                index=index,
                session_id=session_id,
                root_session_id=root_session_id,
                parent_session_id=parent_session_id,
                report=report,
                frozen=froze,
            )
        )
        parent_session_id = session_id
        ran.add(decl.name)

    staged = StagedCalibrationReport(
        phases=tuple(runs),
        frozen=tuple(frozen),
        root_session_id=str(root_session_id),
        protocol=(
            protocol_record(cfg.protocol.name, cfg.protocol) if cfg.protocol is not None else None
        ),
        methods_paragraph=(
            _methods_paragraph_for(cfg, runs, frozen) if cfg.protocol is not None else None
        ),
        restart_spreads=tuple(restart_spreads),
        reused_from_disk=tuple(reused_from_disk),
    )
    return staged if return_report else staged.to_dict()


def _methods_paragraph_for(
    cfg: CalibrationConfig,
    runs: list[PhaseRun],
    frozen: list[FrozenParameter],
) -> str | None:
    """Return the Methods prose for the stages that actually completed."""
    from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

    if cfg.protocol is None:
        return None
    completed = [run.name for run in runs if _converged(run.report)]
    calibrated = {item.name: float(item.value) for item in frozen}
    chosen: dict[str, object] = {}
    for output in (cfg.outputs or {}).values():
        for key in ("tau_specific_ratio", "observed_position_accuracy", "weighting"):
            value = getattr(output, key, None)
            if value is not None:
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
    return methods_paragraph(
        cfg.protocol.name,
        stages_that_ran=completed,
        calibrated=calibrated or None,
        chosen=chosen or None,
        options=protocol_options_away_from_the_recipe(cfg.protocol.name, cfg.protocol) or None,
        conditional_widths=conditional_widths or None,
        absent_widths=absent_widths or None,
    )


__all__ = [
    "FrozenParameter",
    "PhaseRun",
    "StagedCalibrationReport",
    "run_staged_calibration",
]
