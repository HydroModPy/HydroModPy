"""Calibration session journal: the trial history that outlives the index.

Why
---
``.hmp/index.duckdb`` is a rebuildable index, so anything that lives only in
SQL is lost the day it is deleted. A calibration is expensive: dropping its
sessions and trials would turn a rebuild into a data loss, and the
calibration report, which reads those two tables, would stop rendering. The
run directories cannot give the history back either, because a calibration
evaluates far more trials than it promotes to runs.

What
----
Each session owns ``sessions/<name>/`` at the project root:

.. code-block:: text

    sessions/20260726-014233-optuna-3f2a1b7c/
        session.json     identity, project, search space, objective, dates,
                         best trial
        trials.jsonl     one JSON object per evaluated trial, appended live

The journal is written **as the calibration goes**: the descriptor before
the first trial, one line per trial as it completes, and the descriptor once
more at the end with the outcome. An interrupted calibration therefore keeps
every trial it had time to evaluate.

Layer
-----
The format lives in ``results`` because both writers sit on either side of
the layer matrix: ``calibration`` writes the journal while it optimises, and
``results.catalog.reindex`` reads it back into ``calibration_sessions`` and
``calibration_iterations``. The rebuild may not import ``calibration``, so
the shape of a session and of a trial is declared here and used there.

Format
------
.. code-block:: json

    {
      "journal_version": 1,
      "session_id": "3f2a1b7c9d0e4f118a2b5c6d7e8f9012",
      "project": "cheze",
      "method": "optuna",
      "objective_name": "rmse",
      "status": "completed",
      "started_at": "2026-07-26T01:42:33+00:00",
      "ended_at": "2026-07-26T01:44:02+00:00",
      "duration_s": 88.6,
      "best_trial": 2,
      "best_objective": 0.031,
      "best_sim_id": null,
      "error_message": null,
      "search_space": {"K_aquifer": {"bounds": [1e-06, 0.001]}},
      "config": {"method": "optuna", "variable": "head"}
    }

and one trial per line of ``trials.jsonl``:

.. code-block:: json

    {"trial": 2, "status": "completed", "objective_value": 0.031,
     "duration_s": 1.42, "from_cache": false, "params_hash": "v2:9f...",
     "sim_id": null, "parameters": {"K_aquifer": {"value": 9.7e-05}},
     "metrics": {"rmse": 0.031}}

A trial number appearing twice is one trial written twice: the last line
wins, exactly like the upsert the index does on ``(session_id, iteration)``.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.state.paths import SESSIONS_DIRNAME
from hydromodpy.results.storage.contract import (
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_TRIALS_FILENAME,
)

SESSION_JOURNAL_VERSION = 1
"""Schema version of the session journal."""


@dataclass(frozen=True, slots=True)
class SessionTrial:
    """One evaluated trial of a calibration session."""

    trial: int
    parameters: dict[str, Any]
    objective_value: float | None
    status: str
    duration_s: float
    from_cache: bool = False
    metrics: dict[str, Any] | None = None
    params_hash: str | None = None
    sim_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    """Identity, search space and outcome of one calibration session."""

    session_id: str
    project: str
    method: str
    objective_name: str
    started_at: str
    search_space: dict[str, Any]
    config: dict[str, Any]
    status: str = "running"
    ended_at: str | None = None
    duration_s: float | None = None
    best_trial: int | None = None
    best_objective: float | None = None
    best_sim_id: str | None = None
    error_message: str | None = None


def sessions_dir_for(project_root: Path | str) -> Path:
    """Return ``<project>/sessions``, the parent of every session directory."""
    return Path(project_root) / SESSIONS_DIRNAME


def session_dir_name(session_id: str, method: str, started_at: datetime) -> str:
    """Return the directory name of one session, sortable and readable."""
    short = str(session_id).replace("-", "")[:8]
    return f"{started_at:%Y%m%d-%H%M%S}-{method}-{short}"


def session_dirs_for(project_root: Path | str) -> list[Path]:
    """Return every session directory of a project, oldest name first.

    A directory without a descriptor is not a calibration session and is
    ignored: ``sessions/`` also hosts the spin-up sessions.
    """
    root = sessions_dir_for(project_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / SESSION_DESCRIPTOR_FILENAME).is_file())


class SessionJournal:
    """Live on-disk journal of one calibration session.

    :meth:`start` creates the directory and writes the descriptor before the
    first trial, :meth:`append` adds one line per trial, and :meth:`finish`
    rewrites the descriptor with the outcome.
    """

    def __init__(self, directory: Path, descriptor: SessionDescriptor) -> None:
        self._directory = Path(directory)
        self._descriptor = descriptor

    @property
    def directory(self) -> Path:
        """Directory holding the descriptor and the trial journal."""
        return self._directory

    @property
    def descriptor(self) -> SessionDescriptor:
        """Session descriptor as last written to disk."""
        return self._descriptor

    @classmethod
    def start(
        cls,
        project_root: Path | str,
        *,
        session_id: str,
        project: str,
        method: str,
        objective_name: str,
        search_space: dict[str, Any],
        config: dict[str, Any],
        started_at: datetime,
    ) -> SessionJournal:
        """Create ``sessions/<name>/`` and write the opening descriptor.

        ``started_at`` is read once by the caller and shared with the index,
        so a rebuilt session starts at the very instant the live one did.
        """
        directory = sessions_dir_for(project_root) / session_dir_name(
            session_id, method, started_at
        )
        directory.mkdir(parents=True, exist_ok=True)
        journal = cls(
            directory,
            SessionDescriptor(
                session_id=str(session_id),
                project=str(project),
                method=str(method),
                objective_name=str(objective_name),
                started_at=started_at.isoformat(),
                search_space=dict(search_space),
                config=dict(config),
            ),
        )
        journal._write_descriptor()
        return journal

    def append(self, trial: SessionTrial) -> None:
        """Append one trial to ``trials.jsonl``, as soon as it is evaluated."""
        line = json.dumps(_trial_payload(trial), default=str)
        with (self._directory / SESSION_TRIALS_FILENAME).open("a", encoding="utf-8") as stream:
            stream.write(f"{line}\n")

    def finish(
        self,
        *,
        status: str,
        duration_s: float,
        ended_at: datetime,
        best_trial: int | None = None,
        best_objective: float | None = None,
        best_sim_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Rewrite the descriptor with the outcome of the session.

        ``ended_at``, like ``started_at``, is read once by the caller and
        shared with the index.
        """
        self._descriptor = replace(
            self._descriptor,
            status=str(status),
            ended_at=ended_at.isoformat(),
            duration_s=float(duration_s),
            best_trial=None if best_trial is None else int(best_trial),
            best_objective=None if best_objective is None else float(best_objective),
            best_sim_id=None if best_sim_id is None else str(best_sim_id),
            error_message=error_message,
        )
        self._write_descriptor()

    def _write_descriptor(self) -> None:
        """Write ``session.json`` atomically."""
        target = self._directory / SESSION_DESCRIPTOR_FILENAME
        payload = {
            "journal_version": SESSION_JOURNAL_VERSION,
            **_descriptor_payload(self._descriptor),
        }
        tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
        try:
            tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)


def read_descriptor(session_dir: Path | str) -> SessionDescriptor:
    """Read ``session.json`` of one session directory.

    A malformed or incomplete descriptor raises: the rebuild reports the
    session instead of indexing a calibration it cannot describe.
    """
    target = Path(session_dir) / SESSION_DESCRIPTOR_FILENAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} does not hold a session object")
    missing = [
        key
        for key in ("session_id", "project", "method", "objective_name", "started_at")
        if payload.get(key) is None
    ]
    if missing:
        raise ValueError(f"{target} declares no {', '.join(missing)}")
    return SessionDescriptor(
        session_id=str(payload["session_id"]),
        project=str(payload["project"]),
        method=str(payload["method"]),
        objective_name=str(payload["objective_name"]),
        started_at=str(payload["started_at"]),
        search_space=dict(payload.get("search_space") or {}),
        config=dict(payload.get("config") or {}),
        status=str(payload.get("status", "running")),
        ended_at=_text_or_none(payload.get("ended_at")),
        duration_s=_float_or_none(payload.get("duration_s")),
        best_trial=_int_or_none(payload.get("best_trial")),
        best_objective=_float_or_none(payload.get("best_objective")),
        best_sim_id=_text_or_none(payload.get("best_sim_id")),
        error_message=_text_or_none(payload.get("error_message")),
    )


def read_trials(session_dir: Path | str) -> tuple[SessionTrial, ...]:
    """Read ``trials.jsonl``, ordered by trial number, last write per trial.

    A session with no evaluated trial yet carries no journal file and
    returns nothing.
    """
    target = Path(session_dir) / SESSION_TRIALS_FILENAME
    if not target.is_file():
        return ()
    latest: dict[int, SessionTrial] = {}
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict) or "trial" not in payload:
            raise ValueError(f"{target} line {number} holds no trial number")
        trial = SessionTrial(
            trial=int(payload["trial"]),
            parameters=dict(payload.get("parameters") or {}),
            objective_value=_float_or_none(payload.get("objective_value")),
            status=str(payload.get("status", "completed")),
            duration_s=float(payload.get("duration_s") or 0.0),
            from_cache=bool(payload.get("from_cache", False)),
            metrics=dict(payload["metrics"]) if payload.get("metrics") else None,
            params_hash=_text_or_none(payload.get("params_hash")),
            sim_id=_text_or_none(payload.get("sim_id")),
        )
        latest[trial.trial] = trial
    return tuple(latest[key] for key in sorted(latest))


def _descriptor_payload(descriptor: SessionDescriptor) -> dict[str, Any]:
    """Return the JSON object of a session descriptor."""
    return {
        "session_id": descriptor.session_id,
        "project": descriptor.project,
        "method": descriptor.method,
        "objective_name": descriptor.objective_name,
        "status": descriptor.status,
        "started_at": descriptor.started_at,
        "ended_at": descriptor.ended_at,
        "duration_s": descriptor.duration_s,
        "best_trial": descriptor.best_trial,
        "best_objective": descriptor.best_objective,
        "best_sim_id": descriptor.best_sim_id,
        "error_message": descriptor.error_message,
        "search_space": descriptor.search_space,
        "config": descriptor.config,
    }


def _trial_payload(trial: SessionTrial) -> dict[str, Any]:
    """Return the JSON object of one trial line."""
    return {
        "trial": int(trial.trial),
        "status": trial.status,
        "objective_value": trial.objective_value,
        "duration_s": float(trial.duration_s),
        "from_cache": bool(trial.from_cache),
        "params_hash": trial.params_hash,
        "sim_id": trial.sim_id,
        "parameters": trial.parameters,
        "metrics": trial.metrics,
    }


def _text_or_none(value: Any) -> str | None:
    """Return ``value`` as text, or ``None`` when it is absent."""
    return None if value is None else str(value)


def _float_or_none(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is absent."""
    return None if value is None else float(value)


def _int_or_none(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` when it is absent."""
    return None if value is None else int(value)


__all__ = [
    "SESSION_JOURNAL_VERSION",
    "SessionDescriptor",
    "SessionJournal",
    "SessionTrial",
    "read_descriptor",
    "read_trials",
    "session_dir_name",
    "session_dirs_for",
    "sessions_dir_for",
]
