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

A directory tagged :data:`~hydromodpy.results.trash.PROTECTED_TAG`, and one a
live attempt writes into, is never selected.
"""

from __future__ import annotations

import socket
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hydromodpy.core.state.paths import run_dir_rel, runs_dir_for, session_dir_rel, sessions_dir_for
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.manifest import is_sealed, read_manifest
from hydromodpy.results.outcome import (
    Outcome,
    OutcomeError,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME
from hydromodpy.results.trash import (
    TrashedEntry,
    expired_entries,
    is_protected,
    purge_trashed,
    trash_run,
)

TRASH_RETENTION_DAYS = 30
"""Days a trashed directory stays restorable before ``gc --apply`` removes it."""

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


def plan_gc(project_root: Path, policy: RetentionPolicy, *, now: datetime) -> GcPlan:
    """Return what ``gc`` would do in ``project_root``, touching nothing."""
    root = Path(project_root)
    stale: list[str] = []
    eligible: list[_Version] = []
    for run_dir in _dirs(runs_dir_for(root)):
        rel_dir = run_dir_rel(run_dir.name)
        state = effective_status(run_dir, now=now)
        if state == "stale":
            stale.append(rel_dir)
        if state in _LIVE_STATES or is_protected(run_dir):
            continue
        stem, version = split_stem_version(run_dir.name)
        eligible.append(_Version(rel_dir, stem, version or 1, _started_at(run_dir)))

    superseded = _superseded(eligible, policy.keep_versions)
    taken = set(superseded)
    expired: list[str] = []
    if policy.max_age_days is not None:
        cutoff = _as_utc(now) - timedelta(days=policy.max_age_days)
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
    closed = Outcome.model_validate(
        {
            **outcome.model_dump(by_alias=True),
            "status": "aborted",
            "ended_at": _as_utc(now),
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
    descriptor = read_session(session_dir)
    if descriptor.status != "running":
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
    """Return when the run started: its outcome, else its manifest; ``None`` when neither says."""
    outcome = read_outcome(run_dir)
    if outcome is not None:
        return _as_utc(outcome.started_at)
    if is_sealed(run_dir):
        created = read_manifest(run_dir).get("run", {}).get("created_at")
        if created:
            return _as_utc(datetime.fromisoformat(str(created)))
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_KEEP_VERSIONS",
    "TRASH_RETENTION_DAYS",
    "GcPlan",
    "RetentionPolicy",
    "apply_gc",
    "mark_aborted",
    "plan_gc",
]
