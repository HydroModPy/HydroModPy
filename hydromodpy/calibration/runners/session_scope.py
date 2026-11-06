"""The session of a calibration: opening it, scoping its close, promoting its trials.

SIGTERM writes ``aborted``, marks the cut phase, and writes the pointer of the best
trial of the last completed phase (or of the cut phase when no phase completed) in
under a second (:func:`abort_session`); that trial is then promoted from its kept
solve when it has one (:func:`promote_best_after_abort`), anything else is left to
``hmp campaign promote``. The three runners close their session through one scope
(:func:`closing_session`). Nothing here opens the index.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import (
    CalibrationConfig,
)
from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BisectionAdapter,
)
from hydromodpy.calibration.optim.cache import (
    context_fingerprints,
    differing_members,
)
from hydromodpy.calibration.optim.stopping import (
    settled,
)
from hydromodpy.calibration.persistence import (
    DEFAULT_PHASE,
    CalibrationPersistence,
)
from hydromodpy.calibration.protocols import (
    deviations_in_force,
    get_protocol,
)
from hydromodpy.calibration.runners.kept_solves import TrialSolveRetention, retention_capacity
from hydromodpy.calibration.runners.promotion import (
    PromotionOutcome,
    promote_best_after_abort,
    promote_session,
)
from hydromodpy.calibration.runners.recap import (
    cost_metric_label,
    scored_samples,
)
from hydromodpy.calibration.runners.resume import trials_another_cost_scored
from hydromodpy.calibration.runners.sandbox import keep_trial_scratch
from hydromodpy.calibration.runners.session import (
    freeze_session_config,
    open_session_dir,
    search_windows,
    session_bounds,
    session_config_hash,
)
from hydromodpy.calibration.runners.state import (
    build_cache_context,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.core.exceptions import (
    CalibrationError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import TerminationRequested, terminate_as_interrupt
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.checks import CalibrationSessionStatus, StopState
from hydromodpy.results.session.descriptor import (
    BestTrial,
    ParameterWidth,
    ProtocolDeparture,
    ScoredSamples,
    SessionProtocol,
    SessionStatus,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.engine import CalibrationSession
    from hydromodpy.calibration.optim.parameters import ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext


logger = get_logger(__name__)

from hydromodpy.calibration.runners.document import (
    metrics_window_of,
    session_cost_name,
    session_method,
    site_name,
)


def keep_trial_solves(cfg: CalibrationConfig, trial_ctx: TrialContext | None) -> None:
    """Give the session a retention of trial solves when it promotes any.

    A promoted trial then reads the solve its trial left on disk instead of
    being solved again. A session that promotes nothing keeps nothing: each
    trial deletes its solver folder on exit, as before.
    """
    if trial_ctx is None:
        return
    retention = TrialSolveRetention(retention_capacity(cfg))
    trial_ctx.kept_solves = retention if retention.keeps_any else None


def release_trial_solves(trial_ctx: TrialContext | None) -> None:
    """Delete the trial solves the session still keeps, and detach the retention.

    Runs on every exit path, beside :func:`release_session_scratch`, and never
    raises: a folder that cannot be removed is left to the run scratch sweep.
    """
    if trial_ctx is None or trial_ctx.kept_solves is None:
        return
    retention, trial_ctx.kept_solves = trial_ctx.kept_solves, None
    retention.release()


def release_session_scratch(trial_ctx: TrialContext | None) -> None:
    """Drop the preprocessing tree the session shared across its trials.

    Trials skip the setup steps and read the tree built once for the session,
    so no trial may delete it; and only a *promoted* run reaches the export
    step that normally does. A session that promotes nothing therefore used to
    leave hundreds of MB of DEM and flow rasters under ``.hmp/scratch``. This
    runs on every exit path (success, failure, SIGINT) and never raises.

    ``None`` when the named evaluator prepared no model: nothing was built, so
    there is nothing to release.
    """
    from hydromodpy.spatial.geographic.preprocessing_cleanup import cleanup_stable_folder

    if trial_ctx is None:
        return
    geographic = getattr(getattr(trial_ctx.ctx, "setup", None), "geographic", None)
    if geographic is None:
        return
    geographic_cfg = getattr(getattr(trial_ctx, "base_cfg", None), "geographic", None)
    keep = keep_trial_scratch() or bool(getattr(geographic_cfg, "write_intermediates", False))
    try:
        cleanup_stable_folder(geographic, keep=keep)
    except Exception:  # noqa: BLE001 - cleanup never decides the session outcome
        logger.warning("Could not remove the calibration session scratch", exc_info=True)


def root_search_record(session: CalibrationSession | None) -> dict[str, Any] | None:
    """Return the root search's ``bracket`` or ``roots``, None for any other search.

    The session journal keeps this record, so a report read back later shows
    what the live run printed.
    """
    if session is None or not isinstance(session.optimizer, BisectionAdapter):
        return None
    record: dict[str, Any] = {}
    bracket = session.optimizer.bracket_record()
    if bracket is not None:
        record["bracket"] = bracket
    roots = session.optimizer.roots_record()
    if roots is not None:
        record["roots"] = roots
    outside = session.optimizer.root_outside_bounds()
    if outside is not None:
        record["root_outside_bounds"] = outside
    return record or None


def search_status(session: CalibrationSession) -> SessionStatus:
    """Return the status a finished search leaves its phase in.

    ``completed`` when every trial ran and the search settled (its rule met,
    its plan exhausted, or the budget of a search with no rule of its own
    spent); ``partial`` when trials ran but some failed, the budget ended
    before a rule the engine has, or a root closed outside the declared bounds;
    ``failed`` when nothing completed.
    """
    n_total = len(session.history)
    n_ok = sum(1 for item in session.history if item.status in ("completed", "cached"))
    if n_total == 0 or n_ok == 0:
        return "failed"
    if (
        n_ok < n_total
        or not session.settled
        or "root_outside_bounds" in (root_search_record(session) or {})
    ):
        return "partial"
    return "completed"


def session_status_of(reports: Sequence[CalibrationReport]) -> SessionStatus:
    """Return the status of a session from the searches it ran, the worst winning."""
    statuses = [str(report.extra.get("search_status", "completed")) for report in reports]
    if not statuses or "failed" in statuses:
        return "failed"
    if "partial" in statuses:
        return "partial"
    return "completed"


def calibrated_status(status: SessionStatus) -> CalibrationSessionStatus:
    """Return how the seal of a promoted run names the session that promoted it."""
    return "aborted" if status in ("aborted", "failed") else status


def answered_best(
    persistence: CalibrationPersistence, report: CalibrationReport, phase: str
) -> tuple[BestTrial | None, list[ScoredSamples]]:
    """Return the pointer and the scored samples of the trial the search answered with.

    A tie on the cost can set that trial apart from the lowest cost of the journal.
    """
    line = persistence.answered_trial(report.best_trial, phase) or persistence.best_trial(phase)
    case_id = persistence.case_id
    components = None if line is None else line.cases[case_id].components
    return persistence.best_pointer(line), scored_samples(components, case_id=case_id)


def promote_and_close(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    persistence: CalibrationPersistence,
    project_root: Path,
    report: CalibrationReport,
    phase: str,
    status: SessionStatus,
    stop_note: str | None = None,
    widths: Mapping[str, ParameterWidth] | None = None,
) -> CalibrationReport:
    """Promote the trials of ``phase`` and close the session; return the final report.

    ``stop_note`` names the phases of a staged session that froze the best of
    a budget-only search or closed a root outside its bounds, written in
    ``session.json``. ``widths`` is the width of each calibrated value.
    """
    stop_state, stopping_rule = search_stop(report, persistence, phase)
    promotion = PromotionOutcome()
    if trial_ctx is not None and cfg.save_runs != "none" and status != "failed":
        promotion = promote_session(
            cfg=cfg,
            trial_ctx=trial_ctx,
            persistence=persistence,
            project_root=project_root,
            phase=phase,
            session_status=calibrated_status(status),
            override_paths=resolve_override_paths(cfg),
            stop_state=stop_state,
            stopping_rule=stopping_rule,
            answered=report.best_trial,
        )
    final_status: SessionStatus = status
    error: str | None = None
    if promotion.failures:
        # The search is sound and kept; only the written runs are missing.
        final_status = "partial"
        error = "; ".join(promotion.failures)
        logger.error(
            "Promotion failed for %d of %d run(s) of session %s; the search results are "
            "kept, the failed runs were not written.",
            len(promotion.failures),
            len(promotion.failures) + promotion.count,
            persistence.directory.name,
        )
    elif final_status == "partial":
        error = _why_partial(persistence, report, stop_note)
    elif final_status == "failed":
        failed = _failed_trials(persistence)
        error = f"no trial completed; {failed}" if failed else "no trial completed"
    persistence.refresh_phase_best(phase)
    pointer, scored = answered_best(persistence, report, phase)
    descriptor = persistence.finalize_session(
        status=final_status,
        best=pointer,
        error=error,
        root_search={key: report.extra[key] for key in ("bracket", "roots") if key in report.extra},
        scored=scored,
        stop_state=stop_state,
        stopping_rule=stopping_rule,
        stop_note=stop_note,
        widths=widths,
    )
    write_session_readme(persistence)
    extra = dict(report.extra)
    if promotion.failures:
        # Read by the console recap and the CLI exit code. The search itself is
        # sound and kept: only the replayed runs are missing.
        extra["promotion_failures"] = list(promotion.failures)
    return replace(
        report,
        extra=extra,
        status=final_status,
        promoted=promotion.count,
        cost_name=descriptor.cost_name,
        cost_label=descriptor.cost_label,
        best_cases={} if pointer is None else dict(pointer.cases),
        windows=dict(descriptor.windows),
    )


def search_stop(
    report: CalibrationReport, persistence: CalibrationPersistence, phase: str
) -> tuple[StopState | None, str | None]:
    """Return why the search of ``phase`` stopped, and the rule it stops on.

    Read on the search record of the report, or, for a phase reused from disk,
    whose report carries none, on the descriptor of that phase.
    """
    search = report.extra.get("search")
    if isinstance(search, Mapping):
        return search.get("stop_state"), search.get("stopping_rule")
    reused = persistence.phase(phase)
    if reused is not None:
        return reused.stop_state, reused.stopping_rule
    return None, None


def _why_partial(
    persistence: CalibrationPersistence, report: CalibrationReport, note: str | None = None
) -> str:
    """Say why a search closed ``partial``: failed trials, rule not met, what ``note`` says.

    A search can meet its stopping rule and still close ``partial`` because a
    trial failed; the message then names the trials, not the rule.
    """
    failed = _failed_trials(persistence)
    reasons = [failed] if failed else []
    search = report.extra.get("search") or {}
    if search and not settled(search["stop_state"], search["stopping_rule"]):
        reasons.append(f"stopping rule ({search.get('stopping_rule')}) not met")
    if note:
        reasons.append(note)
    return "; ".join(reasons) or "stopping rule not met"


def _failed_trials(persistence: CalibrationPersistence) -> str | None:
    """Name the trials of the session that failed or crashed, the first ten in full."""
    failed = [
        line.trial
        for line in persistence.trials()
        if line.status in ("failed", "crashed", "infeasible")
    ]
    if not failed:
        return None
    shown = ", ".join(str(number) for number in failed[:10])
    more = f" and {len(failed) - 10} more" if len(failed) > 10 else ""
    return f"{len(failed)} trial(s) failed: trial {shown}{more}"


def pointer_phase(persistence: CalibrationPersistence, phase: str) -> str:
    """Return the phase whose best trial a closed session points at.

    The last completed phase, or ``phase``, the one under way, when no phase
    completed.
    """
    completed = [item for item in persistence.phases() if item.status == "completed"]
    return completed[-1].name if completed else phase


def abort_session(persistence: CalibrationPersistence, *, phase: str, error: str) -> str:
    """Write ``aborted``, mark the cut phase, and point at the best trial so far.

    Three small writes and nothing else: the signal that ends the process may
    be followed by one that cannot be caught. ``phase`` is the phase under
    way; its descriptor, when it has one, goes to ``aborted`` with its own
    best trial. Returns the phase the session pointer was read from
    (:func:`pointer_phase`).
    """
    cut = persistence.phase(phase)
    if cut is not None and cut.status == "running":
        persistence.finish_phase(
            phase, status="aborted", best=persistence.best_pointer(persistence.best_trial(phase))
        )
    pointed = pointer_phase(persistence, phase)
    persistence.finalize_session(
        status="aborted",
        best=persistence.best_pointer(persistence.held_trial(pointed)),
        error=error,
        widths=persistence.phase_widths(),
    )
    return pointed


def fail_session(persistence: CalibrationPersistence, *, phase: str, error: str) -> None:
    """Write ``failed`` with the error, pointing at the best trial so far."""
    persistence.finalize_session(
        status="failed",
        best=persistence.best_pointer(persistence.held_trial(pointer_phase(persistence, phase))),
        error=error,
        widths=persistence.phase_widths(),
    )


@dataclass
class SessionScope:
    """What closing a session needs, filled in as a runner goes.

    ``phase`` is the phase under way, the one an interruption cuts, and
    ``trial_ctx`` the prepared model of that phase, whose kept solves and
    scratch are released on every exit. ``persistence`` is None until the
    runner opened the session.
    """

    cfg: CalibrationConfig
    project_root: Path
    persistence: CalibrationPersistence | None = None
    trial_ctx: TrialContext | None = None
    phase: str = DEFAULT_PHASE


@contextmanager
def closing_session(scope: SessionScope) -> Iterator[SessionScope]:
    """Close the session of ``scope`` on every exit the runner did not close itself.

    A signal (SIGTERM, SIGINT) writes ``aborted`` and the pointer first
    (:func:`abort_session`), then promotes the pointed trial from its kept
    solve (:func:`promote_best_after_abort`). An error of the search writes
    ``failed`` with its message. The kept solves and the scratch of the phase
    are released last, after the promotion that reads them.
    """
    try:
        # A calibration is hours long, so what ends it is often not a keyboard: a
        # scheduler time limit, a container stop, a plain kill. All of those are
        # SIGTERM, which by default ends the process where it stands and would
        # leave this session running on disk for good. Here, and not in the search,
        # because restarts side by side run it off the main thread.
        with terminate_as_interrupt():
            yield scope
    except KeyboardInterrupt as exc:
        # TerminationRequested is a KeyboardInterrupt: SIGTERM and SIGINT alike.
        if scope.persistence is not None:
            abort_and_promote(
                scope, error="SIGTERM" if isinstance(exc, TerminationRequested) else "SIGINT"
            )
        raise
    except Exception as exc:
        if scope.persistence is not None:
            fail_session(scope.persistence, phase=scope.phase, error=str(exc))
        raise
    finally:
        if scope.persistence is not None:
            scope.persistence.stop_pulse()
        release_trial_solves(scope.trial_ctx)
        release_session_scratch(scope.trial_ctx)


def abort_and_promote(scope: SessionScope, *, error: str) -> PromotionOutcome:
    """Abort the session of ``scope`` and promote its pointed trial from its kept solve."""
    persistence = scope.persistence
    assert persistence is not None
    pointed = abort_session(persistence, phase=scope.phase, error=error)
    promotion = promote_best_after_abort(
        cfg=scope.cfg,
        trial_ctx=scope.trial_ctx,
        persistence=persistence,
        project_root=scope.project_root,
        phase=pointed,
        override_paths=resolve_override_paths(scope.cfg),
    )
    if promotion.best_sim_id is not None:
        persistence.refresh_phase_best(pointed)
        persistence.set_best(persistence.best_pointer(persistence.held_trial(pointed)))
    for failure in promotion.failures:
        logger.error("Promotion after the interruption failed: %s", failure)
    return promotion


def write_session_readme(persistence: CalibrationPersistence) -> Path:
    """Render ``README.md`` of the session from its descriptor, trials and phases."""
    from hydromodpy.results.readme import render_session_readme, write_readme

    text = render_session_readme(
        persistence.descriptor, persistence.trials(), None, phases=persistence.phases()
    )
    return write_readme(persistence.directory, text)


def refuse_a_phase_another_cost_scored(
    persistence: CalibrationPersistence, phase_name: str, cache_context: Mapping[str, Any]
) -> None:
    """Refuse to add trials to a phase whose earlier trials another cost scored.

    A reopened session (``--resume``, ``--phase``) keeps its journal, and the
    best trial is chosen over every line of the phase. A document changed in
    anything that moves a cost (model, input files, outputs, objective, scoring
    window) would let a trial scored the old way be promoted under the new one.
    A changed budget, method, precision or bound moves no cost and passes.
    """
    differ, unchecked = trials_another_cost_scored(
        persistence, phase_name, cache_context=cache_context
    )
    if differ:
        changed = differing_members(
            persistence.recorded_context(phase_name), context_fingerprints(cache_context)
        )
        raise CalibrationError(
            f"{persistence.directory.name} holds {len(differ)} trial(s) of phase "
            f"{phase_name!r} that this document does not score the same way: "
            f"{', '.join(changed) or 'the cost'} changed since they ran. A session keeps "
            "one cost, so that its best trial is a fair pick. Start a new session (drop "
            "--resume or --phase), or give the variant its own --case."
        )
    if unchecked:
        logger.warning(
            "%d trial(s) of phase %r in %s recorded no fingerprint: this run cannot check "
            "that the same cost scored them.",
            len(unchecked),
            phase_name,
            persistence.directory.name,
        )


def refuse_a_changed_cost(
    persistence: CalibrationPersistence,
    phase_name: str,
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    space: ParameterSpace,
    objective: str | None,
) -> None:
    """Refuse, writing nothing, a reopening whose cost differs from the journal's.

    Run before :meth:`CalibrationPersistence.resume_session` and ``start_phase``,
    so that a refusal leaves the session on disk as it was.
    """
    cache_context = build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=resolve_override_paths(cfg),
        objective_entrypoint=objective,
    )
    refuse_a_phase_another_cost_scored(persistence, phase_name, cache_context)


def open_calibration_session(
    project_root: Path,
    case: str,
    *,
    resume: bool,
    raw: Mapping[str, Any],
    cfg: CalibrationConfig,
    space: ParameterSpace,
    trial_ctx: TrialContext | None,
    project: str | None,
    objective: str | None = None,
) -> tuple[CalibrationPersistence, bool]:
    """Reserve or reopen ``sessions/<case>`` and open its journal.

    A new session freezes the resolved document as ``config.toml`` and writes
    the opening descriptor. A reopened one goes back to ``running`` and keeps
    its trials. Returns the persistence and whether the session was reopened.
    """
    session_dir, reopened = open_session_dir(project_root, case, resume=resume)
    persistence = CalibrationPersistence(session_dir)
    if reopened:
        refuse_a_changed_cost(
            persistence,
            DEFAULT_PHASE,
            cfg=cfg,
            trial_ctx=trial_ctx,
            space=space,
            objective=objective,
        )
        persistence.resume_session()
        persistence.start_pulse()
        return persistence, True
    freeze_session_config(session_dir, raw, cfg)
    persistence.start_session(
        session_id=uuid.uuid4().hex,
        case_id=case,
        site=site_name(raw),
        project=project or project_root.name,
        config_hash=session_config_hash(raw, trial_ctx),
        hydromodpy_version=HYDROMODPY_VERSION,
        method=session_method(cfg),
        cost_name=session_cost_name(cfg),
        # The value the session keeps is the one of its last phase.
        cost_label=cost_metric_label(cfg, cfg.phases[-1] if cfg.phases else None),
        bounds=session_bounds(space, case),
        windows=search_windows(cfg, raw),
        protocol=_protocol_of_session(cfg, trial_ctx, raw),
    )
    persistence.start_pulse()
    return persistence, False


def _protocol_of_session(
    cfg: CalibrationConfig, trial_ctx: TrialContext | None, raw: Mapping[str, Any] | None = None
) -> SessionProtocol | None:
    """Return the protocol a session follows and where it leaves the publication, or None."""
    declared = cfg.protocol
    if declared is None:
        return None
    base_cfg = getattr(trial_ctx, "base_cfg", None)
    departures = [
        ProtocolDeparture(
            key=item.key,
            here=item.here,
            paper=item.paper,
            value=None if item.value is None else str(item.value),
            always=item.state == "always",
            written=item.written,
        )
        for item in deviations_in_force(
            cfg, getattr(base_cfg, "geographic", None), metrics_window_of(raw)
        )
        if item.state in ("always", "departs")
    ]
    protocol = get_protocol(declared.name)
    return SessionProtocol(
        name=protocol.name,
        version=protocol.version if declared.version is None else str(declared.version),
        departures=departures,
    )
