"""What ``hmp catalog gc`` collects in a project, read from the tree alone.

Why
---
The directories are the truth and the index is derived, so a collection that
asks the index what to remove removes what the index believes. Here every
decision reads the project tree: ``outcome.json`` and the heartbeat for the
state of an attempt, ``annotations.json`` for the protected tag, the
``.vN`` suffix for the versions of a name, ``trash/`` for what was deleted.

What
----
A plan has five categories, each applied in a way that can be undone except
the last step of the trash:

- ``stale_runs``: a run whose attempt stopped beating without an outcome.
  Its ``outcome.json`` is rewritten ``aborted``; its ``.hmp/`` is kept for a
  relaunch to resume from.
- ``stale_sessions``: a session whose attempt stopped beating. Its
  ``outcome.json`` and its ``session.json`` are rewritten ``aborted``, so the
  session can be trashed and the index stops showing it as running.
- ``superseded_runs``: the versions of a name beyond the ``keep_versions``
  newest. Moved to the trash.
- ``expired_runs``: the runs started more than ``max_age_days`` ago. Moved
  to the trash.
- ``expired_trash``: the trash entries older than
  :data:`TRASH_RETENTION_DAYS`. Removed, each leaving a tombstone, so its
  name is never given out again.

A directory tagged :data:`~hydromodpy.results.trash.PROTECTED_TAG`, one a live
attempt writes into, and one this code cannot read, is never selected.
"""

from __future__ import annotations

import socket
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from hydromodpy.core.state.layout import runs_dir_for, sessions_dir_for
from hydromodpy.core.state.result_dirs import run_dir_rel, session_dir_rel
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.outcome import (
    Outcome,
    OutcomeError,
    death_is_proven,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.record.manifest import is_sealed, read_seal
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.storage.contract import RUN_OUTCOME_FILENAME, SESSION_DESCRIPTOR_FILENAME
from hydromodpy.results.storage.json_io import beside_seal, readable
from hydromodpy.results.trash import (
    TrashedEntry,
    as_utc,
    expired_entries,
    is_protected,
    purge_trashed,
    trash_run,
)

TRASH_RETENTION_DAYS = 30
"""Days a trashed directory stays restorable before ``gc -y`` removes it."""

DEFAULT_KEEP_VERSIONS = 5
"""Versions of one name ``gc`` keeps by default before trashing the older ones."""

_LIVE_STATES = frozenset({"running", "stale"})


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How much run history ``gc`` keeps in a project.

    Prudent by default: only names with more than :attr:`keep_versions`
    versions are trimmed, and age expiry is opt-in.
    """

    keep_versions: int | None = DEFAULT_KEEP_VERSIONS
    """Newest versions kept per name. ``None`` disables the rule."""

    max_age_days: int | None = None
    """Age past which a run is trashed. ``None`` (default) disables the rule."""


@dataclass(frozen=True, slots=True)
class GcPlan:
    """What ``gc`` would do in one project."""

    project_root: Path
    stale_runs: tuple[str, ...]
    stale_sessions: tuple[str, ...]
    superseded_runs: tuple[str, ...]
    expired_runs: tuple[str, ...]
    expired_trash: tuple[TrashedEntry, ...]

    def categories(self) -> dict[str, list[str]]:
        """Return each category as the relative directories or trash names it holds."""
        return {
            "stale_runs": list(self.stale_runs),
            "stale_sessions": list(self.stale_sessions),
            "superseded_runs": list(self.superseded_runs),
            "expired_runs": list(self.expired_runs),
            "expired_trash": [entry.name for entry in self.expired_trash],
        }


@dataclass(frozen=True, slots=True)
class _Version:
    rel_dir: str
    stem: str
    version: int
    started_at: datetime | None


def _death_is_proven_for(run_dir: Path) -> bool:
    """Whether the attempt of ``run_dir`` ran on this host and its process is gone."""
    outcome = readable(read_outcome, run_dir)
    return outcome is not None and death_is_proven(outcome.host, outcome.pid)


def plan_gc(project_root: Path, policy: RetentionPolicy, *, now: datetime) -> GcPlan:
    """Return what ``gc`` would do in ``project_root``, touching nothing."""
    root = Path(project_root)
    stale: list[str] = []
    eligible: list[_Version] = []
    for run_dir in _dirs(runs_dir_for(root)):
        rel_dir = run_dir_rel(run_dir.name)
        state = effective_status(run_dir, now=now)
        if state == "stale" and _death_is_proven_for(run_dir):
            # A silent heartbeat alone is no proof: the process may live on
            # another host or sit in a long step. Such a run is left running.
            stale.append(rel_dir)
        if state in _LIVE_STATES or state == "unreadable" or is_protected(run_dir):
            continue
        stem, version = split_stem_version(run_dir.name)
        eligible.append(_Version(rel_dir, stem, version or 1, _started_at(run_dir)))

    superseded = _superseded(eligible, policy.keep_versions)
    taken = set(superseded)
    expired: list[str] = []
    if policy.max_age_days is not None:
        cutoff = as_utc(now) - timedelta(days=policy.max_age_days)
        expired = [
            item.rel_dir
            for item in eligible
            if item.rel_dir not in taken
            and item.started_at is not None
            and item.started_at < cutoff
        ]
    old_trash = [
        entry
        for entry in expired_entries(root, older_than=timedelta(days=TRASH_RETENTION_DAYS), now=now)
        if not is_protected(entry.path)
    ]
    stale_sessions = [
        session_dir_rel(session_dir.name)
        for session_dir in _dirs(sessions_dir_for(root))
        if effective_status(session_dir, now=now) == "stale"
    ]
    return GcPlan(
        project_root=root,
        stale_runs=tuple(stale),
        stale_sessions=tuple(stale_sessions),
        superseded_runs=tuple(superseded),
        expired_runs=tuple(expired),
        expired_trash=tuple(old_trash),
    )


def apply_gc(plan: GcPlan, *, now: datetime) -> dict[str, int]:
    """Carry out ``plan`` and return how many directories each category touched."""
    root = plan.project_root
    for rel_dir in plan.stale_runs:
        mark_aborted(root / rel_dir, now=now)
    for rel_dir in plan.stale_sessions:
        _close_session(root / rel_dir, now=now)
    for rel_dir in (*plan.superseded_runs, *plan.expired_runs):
        trash_run(root, rel_dir, now=now)
    purged = purge_trashed(root, list(plan.expired_trash), now=now)
    return {
        "stale_runs": len(plan.stale_runs),
        "stale_sessions": len(plan.stale_sessions),
        "superseded_runs": len(plan.superseded_runs),
        "expired_runs": len(plan.expired_runs),
        "expired_trash": len(purged),
    }


def mark_aborted(run_dir: Path, *, now: datetime) -> Outcome:
    """Rewrite the outcome of a stale attempt as ``aborted`` and return it."""
    outcome = read_outcome(run_dir)
    if outcome is None:
        raise FileNotFoundError(f"{run_dir} holds no outcome.json to close")
    closed = outcome.model_copy(
        update={
            "status": "aborted",
            "ended_at": as_utc(now),
            "written_by": "launcher",
            "error": OutcomeError(
                type="stale",
                message=(
                    f"no heartbeat since the attempt on {outcome.host} (pid {outcome.pid}); "
                    f"closed by gc on {socket.gethostname()}"
                ),
            ),
        }
    )
    write_outcome(run_dir, closed)
    return closed


def _close_session(session_dir: Path, *, now: datetime) -> None:
    """Close a stale session: its outcome, then its descriptor, say ``aborted``."""
    closed = mark_aborted(session_dir, now=now)
    if not (session_dir / SESSION_DESCRIPTOR_FILENAME).is_file():
        return
    descriptor = readable(read_session, session_dir)
    if descriptor is None or descriptor.status != "running":
        return
    assert closed.error is not None
    write_session(
        session_dir,
        descriptor.model_copy(
            update={
                "status": "aborted",
                "ended_at": closed.ended_at,
                "error_message": closed.error.message,
            }
        ),
    )


def _dirs(tree: Path) -> list[Path]:
    if not tree.is_dir():
        return []
    return sorted(entry for entry in tree.iterdir() if entry.is_dir())


def _superseded(versions: list[_Version], keep: int | None) -> list[str]:
    """Return the versions beyond the ``keep`` newest of their name, oldest first."""
    if keep is None:
        return []
    by_stem: dict[str, list[_Version]] = defaultdict(list)
    for item in versions:
        by_stem[item.stem].append(item)
    superseded: list[str] = []
    for _stem, group in sorted(by_stem.items()):
        newest_first = sorted(group, key=lambda item: item.version, reverse=True)
        dropped = sorted(newest_first[keep:], key=lambda item: item.version)
        superseded.extend(item.rel_dir for item in dropped)
    return superseded


def _started_at(run_dir: Path) -> datetime | None:
    """Return when the run started: its outcome, else its seal; ``None`` when neither says.

    A run reaches this function after :func:`effective_status` read its seal, or
    its outcome when it has no seal.
    """
    if not is_sealed(run_dir):
        outcome = read_outcome(run_dir)
        return None if outcome is None else as_utc(outcome.started_at)
    outcome = beside_seal(read_outcome, run_dir, RUN_OUTCOME_FILENAME)
    if outcome is not None:
        return as_utc(outcome.started_at)
    run = read_seal(run_dir).run
    return as_utc(run.started_at or run.created_at)


__all__ = [
    "DEFAULT_KEEP_VERSIONS",
    "TRASH_RETENTION_DAYS",
    "GcPlan",
    "RetentionPolicy",
    "apply_gc",
    "mark_aborted",
    "plan_gc",
]
