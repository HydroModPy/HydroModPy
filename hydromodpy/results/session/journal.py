"""The trial journal of a session: ``sessions/<case>/trials.jsonl``.

Why
---
A calibration evaluates far more trials than it promotes. Their history is
what a resume reuses, what a report draws and what the indexer reads. It is
appended as the search goes, one JSON object per line, so an interrupted
session keeps every trial it had time to evaluate. The trial number is
unique in the session, monotone across phases and restarts: ``trials/0004``
and ``--trial 4`` name one thing.

Format
------
See :class:`TrialLine`. A trial number appearing twice is one trial written
twice (started, then completed): the last line wins. A trailing line without
its newline is the remnant of a crash and is ignored; any other unreadable
line is an error.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import SESSION_TRIALS_FILENAME

TrialStatus = Literal["running", "completed", "failed", "crashed", "aborted"]
"""Where a trial stands."""


class TrialLine(HydroModelBase):
    """One evaluated trial, one line of the journal."""

    trial: int = Field(ge=1, description="Trial number, unique in the session")
    phase: str = Field(description="Phase the trial belongs to")
    restart: int = Field(default=0, ge=0, description="Restart of that phase")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameter values tried")
    params_hash: str | None = Field(default=None, description="Fingerprint of the values")
    objective: float | None = Field(default=None, description="Objective value")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Other metrics of the trial")
    status: TrialStatus
    started_at: datetime = Field(description="Start of the trial, UTC")
    ended_at: datetime | None = Field(default=None, description="End of the trial, UTC")
    sim_id: str | None = Field(default=None, description="Run of a promoted or kept trial")
    rel_dir: str | None = Field(default=None, description="Directory of that run, a hint")

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str | None) -> str | None:
        return None if value is None else checked_rel_dir(value)


def trials_path(session_dir: str | Path) -> Path:
    """Return ``<session>/trials.jsonl``."""
    return Path(session_dir) / SESSION_TRIALS_FILENAME


def append_trial(session_dir: str | Path, line: TrialLine) -> Path:
    """Append one line to the journal, in one write, and return its path."""
    target = trials_path(session_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(line.model_dump(mode="json"), ensure_ascii=False) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return target


def read_trials(session_dir: str | Path) -> list[TrialLine]:
    """Return the trials of a session, one per number, the last line of each winning."""
    target = trials_path(session_dir)
    if not target.is_file():
        return []
    latest: dict[int, TrialLine] = {}
    # The text after the last newline is the remnant of a cut write: never a trial.
    complete = target.read_text(encoding="utf-8").split("\n")[:-1]
    for number, text in enumerate(complete, start=1):
        if not text.strip():
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target}:{number} is not a trial line: {exc}") from exc
        line = TrialLine.model_validate(payload)
        latest[line.trial] = line
    return [latest[number] for number in sorted(latest)]


def next_trial_number(session_dir: str | Path) -> int:
    """Return the number the next trial takes: one above the highest journaled."""
    trials = read_trials(session_dir)
    return 1 if not trials else trials[-1].trial + 1


__all__ = [
    "TrialLine",
    "TrialStatus",
    "append_trial",
    "next_trial_number",
    "read_trials",
    "trials_path",
]
