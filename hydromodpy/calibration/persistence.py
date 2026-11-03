"""The journal of one calibration session, written as the search goes.

A session owns ``sessions/<case>[.vN]/`` at the project root. This module is
the only writer of what the search records there:

- ``outcome.json``: the issue of the session (``running``, then ``completed``,
  ``failed`` or ``aborted``), in the format of a run outcome;
- ``session.json``: identity, cases, bounds, cost, periods, best trial, status
  (:mod:`hydromodpy.results.session.descriptor`);
- ``trials.jsonl``: one line per evaluated trial, numbered once across phases
  and restarts (:mod:`hydromodpy.results.session.journal`);
- ``phases/<phase>/session.json``: status, frozen values and best trial of one
  phase of a staged search (:mod:`hydromodpy.results.session.phase`);
- ``logs/heartbeat.json``: the pulse of the search while it runs, the one a run
  writes (:mod:`hydromodpy.results.heartbeat`).

The journal is written as the calibration goes: the descriptor before the
first trial, one line per trial as it completes, the descriptor again at
every change of status. An interrupted calibration keeps every trial it had
time to evaluate, and the index is rebuilt from these files. Nothing here
opens the index.
"""

from __future__ import annotations

import os
import socket
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.state.paths import process_is_alive
from hydromodpy.results.checks import StopState
from hydromodpy.results.heartbeat import HeartbeatThread
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.outcome import Outcome, OutcomeError, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import (
    BestCase,
    BestTrial,
    ParameterBound,
    ScoredSamples,
    SessionCase,
    SessionDescriptor,
    SessionProtocol,
    SessionStatus,
    read_session,
    session_descriptor_path,
    write_session,
)
from hydromodpy.results.session.journal import (
    TrialCase,
    TrialLine,
    TrialParam,
    append_trial,
    next_trial_number,
    physical_parameters,
    read_trials,
    trial_rows,
)
from hydromodpy.results.session.phase import (
    FrozenValue,
    PhaseDescriptor,
    list_phases,
    phase_dir,
    read_phase,
    write_phase,
)
from hydromodpy.results.storage.attempt import scheduler_job_id_from_env
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

PersistDetail = Literal["none", "summary", "full"]

DEFAULT_PHASE = "main"
"""Phase name of a calibration that declares no ``[[calibration.phases]]``."""


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Which phase of the session a search belongs to, and which restart of it."""

    name: str = DEFAULT_PHASE
    index: int = 0
    restart: int = 0


def _answered_first(lines: Sequence[TrialLine], answered: TrialLine | None) -> list[TrialLine]:
    """Return ranked trials with the one the search answered first, unchanged without it."""
    ranked = list(lines)
    if answered is None:
        return ranked
    return [answered, *(line for line in ranked if line.trial != answered.trial)]


class CalibrationPersistence:
    """Journal writer and reader of one session directory.

    Built on the reserved session directory. :meth:`start_session` writes the
    opening descriptor and outcome, :meth:`append_iteration` adds one line per
    trial, :meth:`finalize_session` closes both documents. A resumed session
    reuses the directory: the trial numbers go on from the highest one journaled.
    """

    def __init__(self, session_dir: Path) -> None:
        self._directory = Path(session_dir)
        self._lock = threading.Lock()
        self._next = next_trial_number(self._directory)
        self._numbers: dict[tuple[str, int, int], int] = {}
        self._outcome: Outcome | None = None
        self._case_id: str | None = None
        self._pulse: HeartbeatThread | None = None

    @property
    def directory(self) -> Path:
        """The session directory."""
        return self._directory

    @property
    def descriptor(self) -> SessionDescriptor:
        """The descriptor as last written to disk."""
        return read_session(self._directory)

    @property
    def case_id(self) -> str:
        """The one case the search scores, read once."""
        if self._case_id is None:
            self._case_id = self.descriptor.case_id
        return self._case_id

    def exists(self) -> bool:
        """Whether the directory already holds a descriptor."""
        return session_descriptor_path(self._directory).is_file()

    def start_pulse(self) -> None:
        """Write ``logs/heartbeat.json`` until :meth:`stop_pulse`, so a live search reads alive."""
        if self._pulse is None and self._outcome is not None:
            self._pulse = HeartbeatThread(self._directory, attempt_id=self._outcome.attempt_id)
            self._pulse.start()

    def stop_pulse(self) -> None:
        """Stop the pulse, if one is running."""
        pulse, self._pulse = self._pulse, None
        if pulse is not None:
            pulse.stop()

    # -- session ----------------------------------------------------------------

    def start_session(
        self,
        *,
        session_id: str,
        case_id: str,
        site: str | None,
        project: str | None,
        config_hash: str,
        hydromodpy_version: str,
        method: str,
        cost_name: str,
        bounds: Mapping[str, ParameterBound],
        windows: Mapping[str, PeriodWindow],
        cost_label: str | None = None,
        protocol: SessionProtocol | None = None,
    ) -> SessionDescriptor:
        """Write the opening descriptor and the running outcome."""
        now = datetime.now(UTC)
        descriptor = SessionDescriptor(
            session_id=session_id,
            case_id=case_id,
            config_hash=config_hash,
            sites=[site] if site else [],
            cases={
                case_id: SessionCase(
                    site=site,
                    config_hash=config_hash,
                    config_file=SESSION_CONFIG_FILENAME,
                    cost_name=cost_name,
                    cost_label=cost_label,
                )
            },
            hydromodpy_version=hydromodpy_version,
            method=method,
            bounds=dict(bounds),
            cost_name=cost_name,
            cost_label=cost_label,
            windows=dict(windows),
            protocol=protocol,
            started_at=now,
        )
        write_session(self._directory, descriptor)
        self._case_id = case_id
        self._outcome = Outcome(
            case_id=case_id,
            site=site,
            project=project,
            attempt=1,
            attempt_id=uuid.uuid4().hex,
            status="running",
            written_by="worker",
            started_at=now,
            host=socket.gethostname(),
            pid=os.getpid(),
            scheduler_job_id=scheduler_job_id_from_env(),
        )
        write_outcome(self._directory, self._outcome)
        return descriptor

    def resume_session(self) -> SessionDescriptor:
        """Reopen an existing session: its status goes back to ``running``.

        A session that another live process of this host still writes is
        refused: two writers would give their trials the same numbers.
        """
        previous = read_outcome(self._directory)
        if previous is not None and previous.status == "running" and _another_live_writer(previous):
            raise CalibrationError(
                f"{self._directory.name} is still written by process {previous.pid} on this "
                "host. Let it end, or stop it, before resuming the session."
            )
        descriptor = read_session(self._directory)
        descriptor = descriptor.model_copy(
            update={"status": "running", "ended_at": None, "error_message": None}
        )
        write_session(self._directory, descriptor)
        self._outcome = Outcome(
            case_id=descriptor.case_id,
            site=descriptor.only_site,
            attempt=1,
            attempt_id=uuid.uuid4().hex,
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host=socket.gethostname(),
            pid=os.getpid(),
            scheduler_job_id=scheduler_job_id_from_env(),
        )
        write_outcome(self._directory, self._outcome)
        return descriptor

    def finalize_session(
        self,
        *,
        status: SessionStatus,
        best: BestTrial | None,
        error: str | None = None,
        root_search: Mapping[str, Any] | None = None,
        scored: Sequence[ScoredSamples] = (),
        stop_state: StopState | None = None,
        stopping_rule: str | None = None,
        stop_note: str | None = None,
    ) -> SessionDescriptor:
        """Close the session: descriptor, then outcome.

        ``scored`` are the pairs the best cost was scored on, kept beside the
        declared ``windows``. ``stop_state`` and
        ``stopping_rule`` say why the search whose best the session holds
        stopped; an interrupted session records none. ``stop_note`` names the
        phases that froze the best of a budget-only search.
        """
        now = datetime.now(UTC)
        descriptor = read_session(self._directory).model_copy(
            update={
                "status": status,
                "ended_at": now,
                "best": best,
                "error_message": error,
                "root_search": dict(root_search) if root_search else None,
                "scored": list(scored),
                "stop_state": stop_state,
                "stopping_rule": stopping_rule,
                "stop_note": stop_note,
            }
        )
        write_session(self._directory, descriptor)
        self._write_closing_outcome(status, error, now)
        return descriptor

    def set_best(self, best: BestTrial | None) -> None:
        """Rewrite the best pointer of the descriptor, status unchanged."""
        descriptor = read_session(self._directory).model_copy(update={"best": best})
        write_session(self._directory, descriptor)

    def refresh_phase_best(self, name: str) -> None:
        """Rewrite the best pointer of a phase once its trial became a run."""
        phase = self.phase(name)
        if phase is not None and phase.best is not None:
            best = self.best_pointer(self.held_trial(name))
            write_phase(self._directory, phase.model_copy(update={"best": best}))

    def record_context(self, phase: str, context: Mapping[str, str]) -> None:
        """Keep the fingerprint of each member of the cache context of ``phase``."""
        descriptor = read_session(self._directory)
        case = descriptor.cases[self.case_id]
        updated = case.model_copy(update={"context": {**case.context, phase: dict(context)}})
        cases = {**descriptor.cases, self.case_id: updated}
        write_session(self._directory, descriptor.model_copy(update={"cases": cases}))

    def recorded_context(self, phase: str) -> dict[str, str]:
        """Return the fingerprints a phase recorded, empty when it recorded none."""
        case = self.descriptor.cases.get(self.case_id)
        return {} if case is None else dict(case.context.get(phase, {}))

    def best_pointer(self, line: TrialLine | None) -> BestTrial | None:
        """Return what a descriptor says of a trial, the values its phase froze included."""
        if line is None:
            return None
        phase = self.phase(line.phase)
        frozen = {} if phase is None else {k: v.value for k, v in phase.frozen.items()}
        return BestTrial(
            trial=line.trial,
            cost=line.cost,
            parameters={**frozen, **physical_parameters(line)},
            cases={
                case_id: BestCase(sim_id=case.sim_id, rel_dir=case.rel_dir, cost=case.cost)
                for case_id, case in line.cases.items()
            },
        )

    def _write_closing_outcome(
        self, status: SessionStatus, error: str | None, now: datetime
    ) -> None:
        outcome = self._outcome
        if outcome is None:
            return
        outcome_status = "completed" if status in ("completed", "partial") else status
        if outcome_status == "completed":
            error_block = None
        else:
            error_block = OutcomeError(type=status, message=error or status)
        self._outcome = outcome.model_copy(
            update={"status": outcome_status, "ended_at": now, "error": error_block}
        )
        write_outcome(self._directory, self._outcome)

    # -- phases -----------------------------------------------------------------

    def start_phase(
        self,
        phase: PhaseContext,
        *,
        frozen: Mapping[str, FrozenValue],
        cost_name: str | None = None,
        cost_label: str | None = None,
        windows: Mapping[str, PeriodWindow] | None = None,
    ) -> PhaseDescriptor:
        """Open a phase, counting a restart when its descriptor already exists."""
        existing = self.phase(phase.name)
        descriptor = PhaseDescriptor(
            phase_id=existing.phase_id if existing is not None else uuid.uuid4().hex,
            name=phase.name,
            index=phase.index,
            status="running",
            frozen=dict(frozen),
            best=None,
            restarts=phase.restart,
            cost_name=cost_name,
            cost_label=cost_label,
            windows=dict(windows or {}),
        )
        write_phase(self._directory, descriptor)
        if self._pulse is not None:
            self._pulse.set_step(phase.name)
        return descriptor

    def finish_phase(
        self,
        name: str,
        *,
        status: SessionStatus,
        best: BestTrial | None,
        scored: Sequence[ScoredSamples] = (),
        stop_state: StopState | None = None,
        stopping_rule: str | None = None,
        stop_note: str | None = None,
    ) -> PhaseDescriptor:
        """Close a phase with its status, its best trial, the restarts it ran and why it stopped."""
        restarts = max((line.restart for line in self.trials(name)), default=0)
        descriptor = read_phase(self._directory, name).model_copy(
            update={
                "status": status,
                "best": best,
                "scored": list(scored),
                "restarts": restarts,
                "stop_state": stop_state,
                "stopping_rule": stopping_rule,
                "stop_note": stop_note,
            }
        )
        write_phase(self._directory, descriptor)
        return descriptor

    def phase(self, name: str) -> PhaseDescriptor | None:
        """Return the descriptor of one phase, or None when it never opened."""
        if not (phase_dir(self._directory, name) / "session.json").is_file():
            return None
        return read_phase(self._directory, name)

    def phases(self) -> list[PhaseDescriptor]:
        """Return every phase of the session, by index."""
        return list_phases(self._directory)

    # -- trials -----------------------------------------------------------------

    def append_iteration(
        self,
        suggestion: ParamSuggestion,
        result: EvaluationResult,
        *,
        detail: PersistDetail = "summary",
        phase: PhaseContext | None = None,
    ) -> TrialLine:
        """Append the line of one evaluated trial and return it.

        The trial number is unique in the session: the first time an engine
        trial id of this phase and restart is seen it takes the next number
        (:meth:`assign_trial_number`).
        """
        context = phase or PhaseContext()
        number = self.assign_trial_number(suggestion.trial_id, context)
        line = _build_trial(number, context, suggestion, result, detail, self.case_id)
        append_trial(self._directory, line)
        return line

    def assign_trial_number(self, engine_trial_id: int, phase: PhaseContext | None = None) -> int:
        """Return the session trial number of an engine trial id, giving it the next one once.

        The engine numbers its trials per search, from its own first id; the
        session numbers them once across phases and restarts. The number is
        given when the trial is first seen, before it runs, so the sandbox of
        the trial and the solve it keeps carry the number its journal line
        carries.
        """
        context = phase or PhaseContext()
        with self._lock:
            key = (context.name, context.restart, int(engine_trial_id))
            number = self._numbers.get(key)
            if number is None:
                number = self._next
                self._next += 1
                self._numbers[key] = number
            return number

    def assign_trial_numbers(
        self, engine_trial_ids: Sequence[int], phase: PhaseContext | None = None
    ) -> list[int]:
        """Number a batch of engine trial ids in the order given, before any of them runs.

        Parallel workers start in no fixed order, so a batch is numbered in the
        order the optimizer made it. Two sessions on the same search then give
        the same trial the same number, and a tie on the objective, broken by
        the smaller number, names the same trial in both.
        """
        return [self.assign_trial_number(trial_id, phase) for trial_id in engine_trial_ids]

    def trial_number(self, engine_trial_id: int, phase: PhaseContext | None = None) -> int | None:
        """Return the session trial number an engine trial id took, or None."""
        context = phase or PhaseContext()
        with self._lock:
            return self._numbers.get((context.name, context.restart, int(engine_trial_id)))

    def trials(self, phase: str | None = None) -> list[TrialLine]:
        """Return the trials of the session, or of one phase, by number."""
        lines = read_trials(self._directory)
        if phase is None:
            return lines
        return [line for line in lines if line.phase == phase]

    def best_trial(
        self, phase: str | None = None, *, restart: int | None = None
    ) -> TrialLine | None:
        """Return the completed trial of lowest finite cost, or None.

        A trial a speculative engine solved and did not read is left out: it
        is not on the path of the search, so the point the search froze is
        not it, and the promoted run must be that point.
        """
        ranked = self._ranked(phase, restart=restart)
        return ranked[0] if ranked else None

    def trial_line(self, number: int | None) -> TrialLine | None:
        """Return the line of one trial, or None."""
        return next((line for line in self.trials() if line.trial == number), None)

    def answered_trial(self, number: int | None, phase: str | None = None) -> TrialLine | None:
        """Return the trial a search answered with its number, or None.

        The answer of a search is not always the lowest number of the lowest cost: a
        bisection answers inside its last bracket, and two trials often share one
        ``abs(J)`` to the last digit. A search that read a point from the cache
        answers with the number of that replay, and the point stays the trial that
        solved it, so the run it became is found. A number out of the ranking is no
        answer: a speculative trial, or no trial at all.
        """
        ranked = self._ranked(phase)
        held = next((line for line in ranked if line.trial == number), None)
        if held is None:
            return None
        return next(line for line in ranked if line.params == held.params)

    def held_trial(self, phase: str) -> TrialLine | None:
        """Return the trial a closed phase holds as its best, the one it passed on.

        It is the answer of its search, which a tie on the cost can set apart from
        the lowest cost. A phase that names none falls back on :meth:`best_trial`.
        """
        descriptor = self.phase(phase)
        held = None if descriptor is None or descriptor.best is None else descriptor.best.trial
        return self.trial_line(held) or self.best_trial(phase)

    def _ranked(self, phase: str | None, *, restart: int | None = None) -> list[TrialLine]:
        """Return the scored trials the search read, lowest cost first."""
        candidates = [
            line
            for line in self.trials(phase)
            if line.status == "completed"
            and line.cost is not None
            and line.cost == line.cost
            and not line.speculative_unused
            and (restart is None or line.restart == restart)
        ]
        return sorted(candidates, key=lambda line: (line.cost, line.trial))

    def link_trial(self, trial: int, *, sim_id: str | None, rel_dir: str | None) -> TrialLine:
        """Rewrite the line of a trial with the run it became; the last line wins."""
        line = next(item for item in read_trials(self._directory) if item.trial == trial)
        case = line.cases[self.case_id].model_copy(update={"sim_id": sim_id, "rel_dir": rel_dir})
        linked = line.model_copy(update={"cases": {**line.cases, self.case_id: case}})
        append_trial(self._directory, linked)
        return linked

    def load_iterations(self, phase: str | None = None) -> list[dict[str, Any]]:
        """Return the trials as plain rows, one per trial number."""
        return [row for line in self.trials(phase) for row in trial_rows(line)]

    def top_n(
        self, n: int, phase: str | None = None, *, answered: int | None = None
    ) -> list[dict[str, Any]]:
        """Return the ``n`` best trials, as rows, ranked like :meth:`best_trial`.

        The first row is the trial the search froze, so the run promoted from it
        is the value the session reports. ``answered`` is the number of the trial
        the search returned, the same rule as :meth:`held_trial`.
        """
        ranked = _answered_first(self._ranked(phase), self.answered_trial(answered, phase))
        return [row for line in ranked[: max(0, int(n))] for row in trial_rows(line)]


def _another_live_writer(outcome: Outcome) -> bool:
    """Whether an outcome names a live process of this host other than this one."""
    return (
        outcome.host == socket.gethostname()
        and outcome.pid != os.getpid()
        and process_is_alive(outcome.pid)
    )


def _trial_params(
    parameters: Mapping[str, Any], values: Mapping[str, float], case_id: str
) -> dict[str, TrialParam]:
    """Return the values a search proposed as a line records them, each target under its case."""
    if not parameters:
        return {name: TrialParam(value=float(value)) for name, value in values.items()}
    params: dict[str, TrialParam] = {}
    for name, entry in parameters.items():
        fields = dict(entry)
        target = fields.pop("target", None)
        params[name] = TrialParam(**fields, targets={case_id: target} if target else {})
    return params


def _build_trial(
    number: int,
    phase: PhaseContext,
    suggestion: ParamSuggestion,
    result: EvaluationResult,
    detail: PersistDetail,
    case_id: str,
) -> TrialLine:
    """Return the journal line one evaluation writes, its one case included."""
    metadata = result.metadata or {}
    parameters = metadata.get("parameters")
    cost = result.cost
    finite = isinstance(cost, (int, float)) and cost == cost
    value = float(cost) if finite else None
    ended_at = datetime.now(UTC)
    duration = max(0.0, float(result.duration_s or 0.0))
    status = "completed" if result.status == "cached" else str(result.status)
    error = metadata.get("error")
    case = TrialCase(
        cost=value,
        components=_kept_components(result, detail),
        status=status,
        params_hash=metadata.get("params_hash"),
        from_cache=bool(result.from_cache) or result.status == "cached",
        sim_id=None if result.from_cache else result.sim_id,
        error=str(error) if error and detail != "none" else None,
        detail=_kept_detail(metadata, detail),
    )
    return TrialLine(
        trial=number,
        phase=phase.name,
        restart=phase.restart,
        params=_trial_params(
            parameters if isinstance(parameters, Mapping) else {},
            dict(suggestion.values),
            case_id,
        ),
        cost=value,
        cases={case_id: case},
        status=status,
        speculative_unused=bool(metadata.get("speculative_unused")),
        started_at=ended_at - timedelta(seconds=duration),
        ended_at=ended_at,
    )


def _kept_components(result: EvaluationResult, detail: PersistDetail) -> dict[str, float]:
    """Return the numbers that make the cost of a trial, at the requested detail."""
    if detail == "none" or not result.components:
        return {}
    return {str(key): float(value) for key, value in dict(result.components).items()}


def _kept_detail(metadata: Mapping[str, Any], detail: PersistDetail) -> dict[str, Any]:
    """Return the free diagnostics of a trial, at the requested detail."""
    if detail == "none":
        return {}
    payload: dict[str, Any] = {}
    overlay = metadata.get("materialized_overlay")
    if overlay:
        payload["materialized_overlay"] = str(overlay)
    if detail == "full":
        block_costs = metadata.get("block_costs")
        if isinstance(block_costs, dict) and block_costs:
            payload["block_costs"] = {str(key): value for key, value in block_costs.items()}
    return payload


__all__ = [
    "DEFAULT_PHASE",
    "CalibrationPersistence",
    "PersistDetail",
    "PhaseContext",
]
