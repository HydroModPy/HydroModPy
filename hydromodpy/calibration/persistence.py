"""The journal of one calibration session, written as the search goes.

A session owns ``sessions/<case>[.vN]/`` at the project root. This module is
the only writer of what the search records there:

- ``outcome.json``: the issue of the session (``running``, then ``completed``,
  ``failed`` or ``aborted``), in the format of a run outcome;
- ``session.json``: identity, search space, objective, best trial, status
  (:mod:`hydromodpy.results.session.descriptor`);
- ``trials.jsonl``: one line per evaluated trial, numbered once across phases
  and restarts (:mod:`hydromodpy.results.session.journal`);
- ``phases/<phase>/session.json``: status, frozen values and best trial of one
  phase of a staged search (:mod:`hydromodpy.results.session.phase`).

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
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.outcome import Outcome, OutcomeError, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import (
    BestTrial,
    ScoredSamples,
    SessionDescriptor,
    SessionStatus,
    read_session,
    session_descriptor_path,
    write_session,
)
from hydromodpy.results.session.journal import (
    TrialLine,
    append_trial,
    next_trial_number,
    read_trials,
    trial_row,
)
from hydromodpy.results.session.phase import (
    PhaseDescriptor,
    list_phases,
    phase_dir,
    read_phase,
    write_phase,
)
from hydromodpy.results.storage.attempt import scheduler_job_id_from_env

PersistDetail = Literal["none", "summary", "full"]

SPECULATIVE_UNUSED = "speculative_unused"
"""Metric key marking a trial a speculative engine solved and did not read."""

DEFAULT_PHASE = "main"
"""Phase name of a calibration that declares no ``[[calibration.phases]]``."""


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Which phase of the session a search belongs to, and which restart of it."""

    name: str = DEFAULT_PHASE
    index: int = 0
    restart: int = 0


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

    @property
    def directory(self) -> Path:
        """The session directory."""
        return self._directory

    @property
    def descriptor(self) -> SessionDescriptor:
        """The descriptor as last written to disk."""
        return read_session(self._directory)

    def exists(self) -> bool:
        """Whether the directory already holds a descriptor."""
        return session_descriptor_path(self._directory).is_file()

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
        objective_name: str,
        search_space: Mapping[str, Any],
        objective_window: DateWindow | None,
        objective_label: str | None = None,
    ) -> SessionDescriptor:
        """Write the opening descriptor and the running outcome."""
        now = datetime.now(UTC)
        descriptor = SessionDescriptor(
            site=site,
            session_id=session_id,
            case_id=case_id,
            config_hash=config_hash,
            hydromodpy_version=hydromodpy_version,
            method=method,
            search_space=dict(search_space),
            objective_name=objective_name,
            objective_label=objective_label,
            objective_window=objective_window,
            started_at=now,
        )
        write_session(self._directory, descriptor)
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
            site=descriptor.site,
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
        objective_samples: Mapping[str, ScoredSamples] | None = None,
    ) -> SessionDescriptor:
        """Close the session: descriptor, then outcome.

        ``objective_samples`` are the pairs the best cost was scored on, kept
        beside the declared ``objective_window``.
        """
        now = datetime.now(UTC)
        descriptor = read_session(self._directory).model_copy(
            update={
                "status": status,
                "ended_at": now,
                "best": best,
                "error_message": error,
                "root_search": dict(root_search) if root_search else None,
                "objective_samples": dict(objective_samples or {}),
            }
        )
        write_session(self._directory, descriptor)
        self._write_closing_outcome(status, error, now)
        return descriptor

    def set_best(self, best: BestTrial | None) -> None:
        """Rewrite the best pointer of the descriptor, status unchanged."""
        descriptor = read_session(self._directory).model_copy(update={"best": best})
        write_session(self._directory, descriptor)

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

    def start_phase(self, phase: PhaseContext, *, frozen: Mapping[str, Any]) -> PhaseDescriptor:
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
        )
        write_phase(self._directory, descriptor)
        return descriptor

    def finish_phase(
        self, name: str, *, status: SessionStatus, best: BestTrial | None
    ) -> PhaseDescriptor:
        """Close a phase with its status, its best trial and the restarts it ran."""
        restarts = max((line.restart for line in self.trials(name)), default=0)
        descriptor = read_phase(self._directory, name).model_copy(
            update={"status": status, "best": best, "restarts": restarts}
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
        line = _build_trial(number, context, suggestion, result, detail)
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
        """Return the completed trial of lowest finite objective, or None.

        A trial a speculative engine solved and did not read is left out: it
        is not on the path of the search, so the point the search froze is
        not it, and the promoted run must be that point.
        """
        ranked = self._ranked(phase, restart=restart)
        return ranked[0] if ranked else None

    def _ranked(self, phase: str | None, *, restart: int | None = None) -> list[TrialLine]:
        """Return the scored trials the search read, lowest objective first."""
        candidates = [
            line
            for line in self.trials(phase)
            if line.status == "completed"
            and line.objective is not None
            and line.objective == line.objective
            and not line.metrics.get(SPECULATIVE_UNUSED)
            and (restart is None or line.restart == restart)
        ]
        return sorted(candidates, key=lambda line: (line.objective, line.trial))

    def link_trial(self, trial: int, *, sim_id: str | None, rel_dir: str | None) -> TrialLine:
        """Rewrite the line of a trial with the run it became; the last line wins."""
        line = next(item for item in read_trials(self._directory) if item.trial == trial)
        linked = line.model_copy(update={"sim_id": sim_id, "rel_dir": rel_dir})
        append_trial(self._directory, linked)
        return linked

    def load_iterations(self, phase: str | None = None) -> list[dict[str, Any]]:
        """Return the trials as plain rows, one per trial number."""
        return [trial_row(line) for line in self.trials(phase)]

    def top_n(self, n: int, phase: str | None = None) -> list[dict[str, Any]]:
        """Return the ``n`` best trials, as rows, ranked like :meth:`best_trial`.

        The first row is the trial the search froze, so the run promoted from it
        is the value the session reports.
        """
        return [trial_row(line) for line in self._ranked(phase)[: max(0, int(n))]]


def _another_live_writer(outcome: Outcome) -> bool:
    """Whether an outcome names a live process of this host other than this one."""
    return (
        outcome.host == socket.gethostname()
        and outcome.pid != os.getpid()
        and process_is_alive(outcome.pid)
    )


def best_pointer(line: TrialLine | None) -> BestTrial | None:
    """Return the descriptor pointer of a trial line, or None."""
    if line is None:
        return None
    return BestTrial(
        trial=line.trial, sim_id=line.sim_id, rel_dir=line.rel_dir, objective=line.objective
    )


def _build_trial(
    number: int,
    phase: PhaseContext,
    suggestion: ParamSuggestion,
    result: EvaluationResult,
    detail: PersistDetail,
) -> TrialLine:
    """Return the journal line one evaluation writes."""
    metadata = result.metadata or {}
    parameters = metadata.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {name: {"value": value} for name, value in dict(suggestion.values).items()}
    objective = result.objective_value
    finite = isinstance(objective, (int, float)) and objective == objective
    ended_at = datetime.now(UTC)
    duration = max(0.0, float(result.duration_s or 0.0))
    status = "completed" if result.status == "cached" else str(result.status)
    return TrialLine(
        trial=number,
        phase=phase.name,
        restart=phase.restart,
        params=parameters,
        params_hash=metadata.get("params_hash"),
        objective=float(objective) if finite else None,
        metrics=_build_metrics(result, metadata, detail),
        status=status,
        from_cache=bool(result.from_cache) or result.status == "cached",
        started_at=ended_at - timedelta(seconds=duration),
        ended_at=ended_at,
        sim_id=result.sim_id,
    )


def _build_metrics(
    result: EvaluationResult,
    metadata: Mapping[str, Any],
    detail: PersistDetail,
) -> dict[str, Any]:
    """Return the metric payload of one trial at the requested detail.

    The mark of a speculative trial is kept at every detail: the best trial
    is chosen on it.
    """
    # A speculative engine solved this candidate and its rules did not read it:
    # the trial is real, but it is not on the path of the search.
    speculative = {SPECULATIVE_UNUSED: 1.0} if metadata.get("speculative_unused") else {}
    if detail == "none":
        return speculative
    payload: dict[str, Any] = {}
    if result.components:
        payload.update({str(key): value for key, value in dict(result.components).items()})
    overlay = metadata.get("materialized_overlay")
    if overlay:
        payload["materialized_overlay"] = str(overlay)
    if detail == "full":
        block_costs = metadata.get("block_costs")
        if isinstance(block_costs, dict) and block_costs:
            payload["block_costs"] = {str(key): value for key, value in block_costs.items()}
    error = metadata.get("error")
    if error:
        payload["error"] = str(error)
    payload.update(speculative)
    return payload


__all__ = [
    "DEFAULT_PHASE",
    "CalibrationPersistence",
    "PersistDetail",
    "PhaseContext",
    "best_pointer",
]
