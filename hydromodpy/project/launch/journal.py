"""The folder of one launch, ``jobs/<stamp>-<scheduler>/``, and its journal.

Why
---
A launch leaves a visible trace that ``rm -rf .hmp`` does not destroy: what
was asked, which cases started, how each one ended. The local launcher
writes ``journal.jsonl``, one JSON object per event, appended and flushed
line by line, never rewritten. A scheduler job writes ``cases.txt``, the
frozen list of the case files its tasks read; its journal is rebuilt from
the outcomes of those cases by :func:`read_journal`.

Events
------
Every line carries ``event`` and ``at`` (UTC, ISO 8601). The launcher writes
``launch_start``, ``prepare_start`` / ``prepare_end`` per case,
``lockfile``, ``case_start`` / ``case_end`` per case, ``case_skipped`` and
``launch_end``. A ``case_end`` carries ``case_id``, ``status``,
``exit_code``, ``signal``, ``rel_dir``, ``error`` and ``log_tail``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.state.layout import jobs_dir_for

JOURNAL_FILENAME = "journal.jsonl"
"""Journal of a local launch, ``jobs/<stamp>-local/journal.jsonl``."""

CASES_FILENAME = "cases.txt"
"""Frozen case list of a scheduler job: one case file per line, relative to the project."""

CASE_LOGS_DIRNAME = "logs"
"""Standard output of each child process, ``jobs/<stamp>-local/logs/<case>.log``."""

CASE_CACHES_DIRNAME = "caches"
"""Private data caches of the children, ``jobs/<stamp>-local/caches/<case>/``, until merged."""

FAILED_STATUSES = frozenset({"failed", "aborted", "stale"})
"""Statuses ``hmp project log --failed`` keeps."""

STAMP_FORMAT = "%Y%m%d-%H%M%S"
"""Format of the stamp that starts the name of a job folder."""


def job_stamp(now: datetime | None = None) -> str:
    """Return the stamp of a job started at *now* (UTC)."""
    return (now if now is not None else datetime.now(UTC)).strftime(STAMP_FORMAT)


def new_job_dir(project_root: Path, scheduler: str, *, now: datetime | None = None) -> Path:
    """Create and return ``jobs/<stamp>-<scheduler>/``; a taken name gets a suffix."""
    jobs = jobs_dir_for(Path(project_root))
    jobs.mkdir(parents=True, exist_ok=True)
    base = f"{job_stamp(now)}-{scheduler}"
    for index in range(1000):
        name = base if index == 0 else f"{base}.{index}"
        try:
            (jobs / name).mkdir()
        except FileExistsError:
            continue
        return jobs / name
    raise FileExistsError(f"no free job folder name under {jobs} for {base}")


def job_dirs(project_root: Path) -> list[Path]:
    """Return the job folders of a project, oldest first."""
    jobs = jobs_dir_for(Path(project_root))
    if not jobs.is_dir():
        return []
    return sorted(path for path in jobs.iterdir() if path.is_dir())


def _job_dir_of(project_root: Path, job: str | Path) -> Path:
    """Return the folder of *job*: a path, or a folder name under ``jobs/``.

    Raises :class:`FileNotFoundError` naming the jobs the project has.
    """
    candidate = Path(job).expanduser()
    if candidate.is_dir():
        return candidate.resolve()
    named = jobs_dir_for(Path(project_root)) / str(job)
    if named.is_dir():
        return named
    known = ", ".join(path.name for path in job_dirs(project_root)) or "none"
    raise FileNotFoundError(
        f"no job {job!r} under {jobs_dir_for(Path(project_root))}; jobs: {known}"
    )


class Journal:
    """The append-only journal of one local launch."""

    def __init__(self, job_dir: Path) -> None:
        self._path = Path(job_dir) / JOURNAL_FILENAME

    @property
    def path(self) -> Path:
        """``jobs/<stamp>-local/journal.jsonl``."""
        return self._path

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        """Append one event line, flushed to disk, and return it."""
        line = {"event": event, "at": datetime.now(UTC).isoformat(), **fields}
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return line


def _read_events(path: Path) -> list[dict[str, Any]]:
    """Return the events of one journal file; a torn last line is skipped."""
    events: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return events
    for text in lines:
        if not text.strip():
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # A launcher killed while writing leaves half a line; the rest stands.
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def write_case_list(job_dir: Path, case_files: Sequence[str]) -> Path:
    """Write ``cases.txt``: one case file per line, relative to the project root."""
    path = Path(job_dir) / CASES_FILENAME
    path.write_text("".join(f"{entry}\n" for entry in case_files), encoding="utf-8")
    return path


def read_case_list(job_dir: Path) -> list[str]:
    """Return the case files of ``cases.txt``, in order."""
    path = Path(job_dir) / CASES_FILENAME
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def case_for_task(project_root: Path, job: str | Path, task_id: int) -> Path:
    """Return the case file of task *task_id* of *job*; the first line is task 1.

    Raises :class:`IndexError` naming the size of the list.
    """
    root = Path(project_root).resolve()
    entries = read_case_list(_job_dir_of(root, job))
    if not 1 <= task_id <= len(entries):
        raise IndexError(f"task {task_id} is outside the job, whose cases are 1..{len(entries)}")
    return root / entries[task_id - 1]


def read_journal(
    project_root: Path, *, failed_only: bool = False, job: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return the events of the latest launch of a project, or of *job*.

    A local launch is read from its ``journal.jsonl``. A scheduler job, which
    has a ``cases.txt`` and no journal, is rebuilt from the ``outcome.json``
    of its cases: one ``case_end`` per case that has a directory.
    *failed_only* keeps the last ``case_end`` of every case that ended
    failed, aborted or stale, one line per case.
    """
    root = Path(project_root).resolve()
    if job is not None:
        chosen: Path | None = _job_dir_of(root, job)
    else:
        candidates = [
            path
            for path in job_dirs(root)
            if (path / JOURNAL_FILENAME).is_file() or (path / CASES_FILENAME).is_file()
        ]
        chosen = candidates[-1] if candidates else None
    if chosen is None:
        return []
    if (chosen / JOURNAL_FILENAME).is_file():
        events = _read_events(chosen / JOURNAL_FILENAME)
    else:
        events = _rebuild_from_outcomes(root, chosen)
    if not failed_only:
        return events
    last: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") in ("case_end", "prepare_end") and event.get("case_id"):
            last[str(event["case_id"])] = event
    return [event for event in last.values() if event.get("status") in FAILED_STATUSES]


def _rebuild_from_outcomes(project_root: Path, job_dir: Path) -> list[dict[str, Any]]:
    from hydromodpy.project.launch.status import case_state

    events: list[dict[str, Any]] = []
    for entry in read_case_list(job_dir):
        case_id = Path(entry).stem
        state = case_state(project_root, case_id)
        if state.status == "planned":
            continue
        events.append(_case_end_of(case_id, state.status, state.rel_dir, state.outcome))
    return events


def _case_end_of(
    case_id: str, status: str, rel_dir: str | None, outcome: Mapping[str, Any] | None
) -> dict[str, Any]:
    outcome = outcome or {}
    error = outcome.get("error") or None
    return {
        "event": "case_end",
        "at": outcome.get("ended_at") or outcome.get("started_at"),
        "case_id": case_id,
        "status": status,
        "rel_dir": rel_dir,
        "exit_code": outcome.get("exit_code"),
        "signal": outcome.get("signal"),
        "error": error,
        "log_tail": list(outcome.get("log_tail") or []),
    }


__all__ = [
    "CASES_FILENAME",
    "CASE_CACHES_DIRNAME",
    "CASE_LOGS_DIRNAME",
    "FAILED_STATUSES",
    "JOURNAL_FILENAME",
    "STAMP_FORMAT",
    "Journal",
    "case_for_task",
    "job_dirs",
    "job_stamp",
    "new_job_dir",
    "read_case_list",
    "read_journal",
    "write_case_list",
]
