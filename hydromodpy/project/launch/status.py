"""Where each case of the current plan stands, read from the disk alone.

Why
---
``hmp project status`` answers from ``plan/current`` and from the
directories of the cases, never from the index. The state of an attempt is
the one its directory says (``outcome.json``, the pulse of
``logs/heartbeat.json``, ``manifest.json``): running, completed, partial,
failed, aborted or stale. The states of the plan are computed here and
never written anywhere: ``planned`` (no directory yet), ``stale_plan`` (the
files the plan was made from changed since, and the case has not run),
``invalid`` (the case no longer validates against the changed files) and
``skipped`` (the last launch stopped before it, ``[sites.run] on_error =
"raise"``). A case without a directory whose prepare phase failed, or whose
worker was refused before its claim (``--frozen``), is ``failed``, as the
journal of the latest launch says. On a cluster, a running attempt whose task
``sacct`` reports ended is ``failed``: the worker died without a word.

A calibration case is its session ``sessions/<case>/`` until the session is
completed; then it is the run the session promoted, ``runs/<case>/``. A
session whose descriptor still says ``running`` reads as its outcome does:
``stale`` when its worker is dead or silent, ``failed`` or ``aborted`` when
the outcome was closed and the descriptor was not.

A session or a run this code cannot read, written by another version, costs
one warning and is left out. A case left with nothing readable is ``planned``:
it is not done, and running it takes a new version beside the one left out.
A sealed run whose outcome this code cannot read stays ``completed``, with what
its seal says of the attempt. A plan this code cannot read is refused, because
without it no case is known.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, runs_dir_for
from hydromodpy.core.state.result_dirs import run_dir_rel, session_dir_rel
from hydromodpy.results.outcome import (
    DEFAULT_STALE_AFTER_S,
    EffectiveStatus,
    effective_status,
    read_outcome,
)
from hydromodpy.results.plan_store import StoredPlan, read_plan
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.session.descriptor import latest_session_dir
from hydromodpy.results.storage.attempt import latest_version_dir
from hydromodpy.results.storage.contract import RUN_OUTCOME_FILENAME
from hydromodpy.results.storage.json_io import beside_seal, readable

CaseStatus = Literal[
    "planned",
    "invalid",
    "skipped",
    "stale_plan",
    "running",
    "completed",
    "partial",
    "failed",
    "aborted",
    "stale",
]
"""What ``hmp project status`` says about one case."""

PLAN_STATES: frozenset[str] = frozenset({"planned", "invalid", "skipped", "stale_plan"})
"""States of the plan, never written in the index."""


@dataclass(frozen=True, slots=True)
class CaseState:
    """What the directories of one case say."""

    status: CaseStatus
    rel_dir: str | None = None
    outcome: dict[str, Any] | None = None
    session_hash: str | None = None
    """The configuration hash the latest session of a calibration case recorded."""


@dataclass(frozen=True, slots=True)
class StatusRow:
    """One case of the plan and where it stands."""

    case_id: str
    site: str | None
    recipe: str | None
    status: CaseStatus
    rel_dir: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    pid: int | None = None
    host: str | None = None
    attempt: int | None = None
    step: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StatusReport:
    """The status of every case of the current plan."""

    project_root: Path
    plan_hash: str
    plan_stale: bool
    rows: tuple[StatusRow, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, int]:
        """Return the number of cases per status, in the order of the rows."""
        out: dict[str, int] = {}
        for row in self.rows:
            out[row.status] = out.get(row.status, 0) + 1
        return out


def _run_state(run_dir: Path, *, now: datetime, stale_after_s: float) -> EffectiveStatus:
    status = effective_status(run_dir, now=now, stale_after_s=stale_after_s)
    if status != "unknown":
        return status
    # A directory without outcome is a claim in flight while it is young.
    age = (now - datetime.fromtimestamp(run_dir.stat().st_mtime, tz=UTC)).total_seconds()
    return "running" if age <= stale_after_s else "stale"


def _outcome_document(directory: Path) -> dict[str, Any] | None:
    """Return what the outcome says, else what a seal says of the attempt.

    Called once the seal or the descriptor of *directory* was read, so an
    outcome this code cannot read takes nothing from its status.
    """
    outcome = beside_seal(read_outcome, directory, RUN_OUTCOME_FILENAME)
    if outcome is not None:
        return outcome.model_dump(mode="json", by_alias=True)
    seal = readable(read_seal, directory)
    if seal is None:
        return None
    return {
        "attempt": seal.run.attempt,
        "started_at": seal.run.started_at,
        "ended_at": seal.run.ended_at,
    }


def case_state(
    project_root: Path,
    case_id: str,
    *,
    now: datetime | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> CaseState:
    """Return what the directories of *case_id* say, its session first."""
    from hydromodpy.results.session.descriptor import read_session, session_descriptor_path

    root = Path(project_root)
    instant = now if now is not None else datetime.now(UTC)
    run_dir = latest_version_dir(root, case_id)
    session_dir = latest_session_dir(root, case_id)
    descriptor = None
    if session_dir is not None and session_descriptor_path(session_dir).is_file():
        descriptor = readable(read_session, session_dir)
    if session_dir is not None and descriptor is not None:
        session_rel = session_dir_rel(session_dir.name)
        session_hash = descriptor.config_hash
        if descriptor.status == "running":
            live = _run_state(session_dir, now=instant, stale_after_s=stale_after_s)
            # A worker this code cannot read may still be alive: it is held like a silent one.
            held: CaseStatus = "stale" if live == "unreadable" else "running"
            if live in ("stale", "failed", "aborted"):
                held = live
            return CaseState(held, session_rel, _outcome_document(session_dir), session_hash)
        if descriptor.status != "completed":
            return CaseState(
                descriptor.status, session_rel, _outcome_document(session_dir), session_hash
            )
        promoted = runs_dir_for(root) / session_dir.name
        if not promoted.is_dir():
            return CaseState("partial", session_rel, _outcome_document(session_dir), session_hash)
        run_dir = promoted
    if run_dir is None:
        return CaseState("planned")
    status = _run_state(run_dir, now=instant, stale_after_s=stale_after_s)
    if status == "unreadable":
        return CaseState("planned")
    return CaseState(status, run_dir_rel(run_dir.name), _outcome_document(run_dir))


def plan_is_stale(project_root: Path, stored: StoredPlan) -> bool:
    """Whether a file the plan was made from changed or disappeared since."""
    root = Path(project_root)
    for name, digest in stored.plan.fingerprints.items():
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return True
        if current != digest:
            return True
    return False


def _invalid_cases(project_root: Path) -> set[str]:
    """Return the cases of the project that no longer validate."""
    from hydromodpy.project.launch.sites.expansion import expand_plan

    root = Path(project_root)
    draft = expand_plan(root, root / PROJECT_MARKER_FILENAME)
    return {issue.case_id for issue in draft.errors if issue.case_id}


def _journal_states(project_root: Path) -> dict[str, CaseStatus]:
    """Return what the latest launch says of the cases that left no directory.

    ``skipped`` when the launch stopped before the case; ``failed`` when its
    prepare phase failed, or when its worker ended without claiming a
    directory (a ``--frozen`` refusal, a configuration it refused).
    """
    from hydromodpy.project.launch.journal import read_journal

    states: dict[str, CaseStatus] = {}
    for event in read_journal(project_root):
        case_id = event.get("case_id")
        if not case_id:
            continue
        kind = event.get("event")
        if kind == "case_skipped":
            states[str(case_id)] = "skipped"
        elif kind in ("prepare_end", "case_end") and event.get("status") == "failed":
            states[str(case_id)] = "failed"
        elif kind in ("prepare_start", "prepare_end", "case_start", "case_end"):
            states.pop(str(case_id), None)
    return states


def project_status(
    project_root: Path, *, stale_after_s: float = DEFAULT_STALE_AFTER_S
) -> StatusReport:
    """Return the status of every case of the current plan of *project_root*.

    Raises :class:`FileNotFoundError` when the project has no plan.
    """
    root = Path(project_root).resolve()
    try:
        stored = read_plan(root)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{root} has no plan; write one with `hmp project plan .`") from exc
    stale = plan_is_stale(root, stored)
    invalid = _invalid_cases(root) if stale else set()
    journal = _journal_states(root)
    now = datetime.now(UTC)
    # Function level: sacct imports slurm, which imports plan_is_stale from this module.
    from hydromodpy.project.launch.sacct import scheduler_states

    scheduler = scheduler_states(root)
    rows: list[StatusRow] = []
    for case in stored.cases:
        state = case_state(root, case.case_id, now=now, stale_after_s=stale_after_s)
        status = state.status
        ended = scheduler.get(case.case_id)
        if (
            status in ("running", "stale")
            and ended is not None
            and ended.finished
            and (state.outcome or {}).get("scheduler_job_id") == ended.job_id
        ):
            # The scheduler says the task ended: the worker died without a word (D7).
            status = "failed"
        if status == "planned":
            if case.case_id in invalid:
                status = "invalid"
            elif stale:
                status = "stale_plan"
            elif case.case_id in journal:
                status = journal[case.case_id]
        rows.append(_row(case.case_id, case.site, case.recipe, status, state))
    return StatusReport(
        project_root=root, plan_hash=stored.plan.plan_hash, plan_stale=stale, rows=tuple(rows)
    )


def _row(
    case_id: str, site: str | None, recipe: str | None, status: CaseStatus, state: CaseState
) -> StatusRow:
    outcome = state.outcome or {}
    error = outcome.get("error") or None
    return StatusRow(
        case_id=case_id,
        site=site,
        recipe=recipe,
        status=status,
        rel_dir=state.rel_dir,
        started_at=_instant(outcome.get("started_at")),
        ended_at=_instant(outcome.get("ended_at")),
        pid=outcome.get("pid"),
        host=outcome.get("host"),
        attempt=outcome.get("attempt"),
        step=outcome.get("step"),
        error=None if error is None else f"{error.get('type')}: {error.get('message')}",
    )


def _instant(value: Any) -> datetime | None:
    if value is None:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


__all__ = [
    "PLAN_STATES",
    "CaseState",
    "CaseStatus",
    "StatusReport",
    "StatusRow",
    "case_state",
    "plan_is_stale",
    "project_status",
]
