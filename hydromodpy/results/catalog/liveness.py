"""Read the liveness of the runs and sessions of a project from its directories.

``watch``, and the counts ``hmp doctor`` prints, read the ``outcome.json`` and
``logs/heartbeat.json`` of the directories and never open the index: a status
page must answer while the index is being rebuilt or when a project has none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S

ABANDONED_SESSION_MINUTES = 24 * 60
"""How long a session may sit ``running`` before it is counted as abandoned.

A day, deliberately generous: a calibration on a daily chronicle runs for
hours, and counting a live one would be worse than missing a dead one.
"""


def _attempt_dirs(project_root: Path) -> list[tuple[str, Path]]:
    """Return ``(rel_dir, path)`` of every directory carrying an outcome."""
    from hydromodpy.results.catalog.indexer import scan_tree

    return [
        (entry.rel_dir, entry.path)
        for entry in scan_tree(project_root).values()
        if entry.kind != "session"
    ]


def watch_running(workspace: Any, *, stale_minutes: float | None = None) -> list[dict]:
    """Return the running attempts of a project with the age of their pulse.

    Reads ``outcome.json`` and ``logs/heartbeat.json`` only, never the index.
    An attempt is ``stale`` when its pulse is older than ``stale_minutes``
    (default :data:`~hydromodpy.results.outcome.DEFAULT_STALE_AFTER_S`),
    which is a display word: only a proven death lets another attempt take
    the directory.
    """
    from hydromodpy.results.heartbeat import read_heartbeat
    from hydromodpy.results.outcome import effective_status, read_outcome
    from hydromodpy.results.storage.json_io import readable

    root = Path(workspace).expanduser().resolve()
    stale_after_s = DEFAULT_STALE_AFTER_S if stale_minutes is None else stale_minutes * 60.0
    now = datetime.now(UTC)
    rows: list[dict] = []
    for rel_dir, path in _attempt_dirs(root):
        status = effective_status(path, now=now, stale_after_s=stale_after_s)
        if status not in ("running", "stale"):
            continue
        outcome = readable(read_outcome, path)
        if outcome is None:
            continue
        beat = readable(read_heartbeat, path)
        age_s = None if beat is None else max(0.0, (now - beat.at).total_seconds())
        rows.append(
            {
                "rel_dir": rel_dir,
                "case_id": outcome.case_id,
                "sim_id": outcome.sim_id,
                "attempt": outcome.attempt,
                "attempt_id": outcome.attempt_id,
                "host": outcome.host,
                "pid": outcome.pid,
                "step": None if beat is None else beat.step or outcome.step,
                "started_at": outcome.started_at,
                "heartbeat_at": None if beat is None else beat.at,
                "age_s": age_s,
                "stale": status == "stale",
            }
        )
    rows.sort(key=lambda row: row["rel_dir"])
    return rows


def stale_running_sim_ids(project_root: Path, minutes: float | None = None) -> list[str]:
    """Return the ``rel_dir`` of every attempt whose pulse is older than ``minutes``."""
    return [
        row["rel_dir"] for row in watch_running(project_root, stale_minutes=minutes) if row["stale"]
    ]


def _session_descriptors(project_root: Path) -> list[tuple[Path, Any]]:
    from hydromodpy.results.session.descriptor import list_session_dirs, read_session
    from hydromodpy.results.storage.json_io import readable_documents

    return list(readable_documents(read_session, list_session_dirs(project_root)))


def abandoned_calibration_session_count(project_root: Path) -> int:
    """Count the sessions still ``running`` more than a day after they started."""
    cutoff = datetime.now(UTC) - timedelta(minutes=ABANDONED_SESSION_MINUTES)
    return sum(
        1
        for _path, descriptor in _session_descriptors(project_root)
        if descriptor.status == "running" and descriptor.started_at < cutoff
    )


def orphan_calibration_session_count(project_root: Path) -> int:
    """Count the sessions whose best run directory no longer exists."""
    root = Path(project_root)
    count = 0
    for _path, descriptor in _session_descriptors(root):
        best = descriptor.best
        cases = () if best is None else best.cases.values()
        if any(case.rel_dir is not None and not (root / case.rel_dir).is_dir() for case in cases):
            count += 1
    return count


__all__ = [
    "ABANDONED_SESSION_MINUTES",
    "abandoned_calibration_session_count",
    "orphan_calibration_session_count",
    "stale_running_sim_ids",
    "watch_running",
]
