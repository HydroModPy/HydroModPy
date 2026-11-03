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
See :class:`TrialLine`; every line carries the schema id
:data:`TRIAL_SCHEMA`. What a trial gave in each case sits under ``cases``, keyed
by ``case_id``, one entry for a session of one case. ``cost`` is the number the
search minimised, null on a failed trial or when the search keeps no single
cost. A trial number appearing twice is one trial written twice (started, then
completed): the last line wins. A trailing line without its newline is the
remnant of a crash and is ignored; any other unreadable line is an error.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary, dump_stored, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import SESSION_TRIALS_FILENAME
from hydromodpy.results.storage.json_io import check_sealed

TRIAL_SCHEMA: Final[str] = "hydromodpy.trial.v2"
"""Schema id of one line of ``trials.jsonl``."""

TRIAL_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.trial.v2", current=TRIAL_SCHEMA
)
"""Versions of one line of the journal this code reads."""

TrialStatus = Annotated[
    str, Vocabulary("running", "completed", "failed", "crashed", "infeasible", "aborted")
]
"""Where a trial stands. ``infeasible`` is a point the search may leave, not a crash."""


class TrialParam(HydroModelBase):
    """One value a search proposed. Only ``value`` is always there."""

    value: float = Field(description="Physical value tried")
    transformed_value: float | None = Field(default=None, description="Value in the search space")
    bounds: tuple[float, float] | None = Field(default=None, description="Physical bounds")
    transformed_bounds: tuple[float, float] | None = Field(
        default=None, description="Bounds in the search space"
    )
    search_space: str | None = Field(default=None, description="identity, log or logit")
    sampling: str | None = Field(default=None, description="How the search samples it")
    mode: str | None = Field(default=None, description="replace or scale")
    units: str | None = Field(default=None, description="Unit of the physical value")
    targets: dict[str, str] = Field(
        default_factory=dict, description="Address of the value in each case, by case id"
    )


class TrialCase(HydroModelBase):
    """What one trial gave in one case."""

    cost: float | None = Field(default=None, description="Cost of this case")
    components: dict[str, float] = Field(
        default_factory=dict,
        description="The numbers that make this cost, the only ones a cached trial reads back",
    )
    status: TrialStatus = Field(description="Issue of this case")
    params_hash: str | None = Field(default=None, description="Cache key of this case")
    from_cache: bool = Field(
        default=False,
        description="True when the cost came from an earlier trial with the same hash",
    )
    sim_id: str | None = Field(
        default=None, description="Run of this trial in this case, never another session's"
    )
    rel_dir: str | None = Field(default=None, description="Directory of that run, a hint")
    error: str | None = Field(default=None, description="Why this case did not complete")
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Free diagnostics, such as materialized_overlay and block_costs",
    )

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str | None) -> str | None:
        return None if value is None else checked_rel_dir(value)


class TrialLine(HydroModelBase):
    """One evaluated trial, one line of the journal."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=TRIAL_SCHEMA, alias="schema", description="Schema id")
    trial: int = Field(ge=1, description="Trial number, unique in the session")
    phase: str = Field(description="Phase the trial belongs to")
    restart: int = Field(default=0, ge=0, description="Restart of that phase")
    params: dict[str, TrialParam] = Field(
        default_factory=dict, description="Values the search proposed, by parameter"
    )
    cost: float | None = Field(
        default=None,
        description="The number the search minimised, null for a failed trial or when the "
        "search keeps no single cost",
    )
    cases: dict[str, TrialCase] = Field(
        default_factory=dict, description="What the trial gave in each case, by case id"
    )
    status: TrialStatus = Field(description="Where the trial stands")
    speculative_unused: bool = Field(
        default=False,
        description="True for a trial a speculative engine solved and did not read: it is "
        "kept and it leaves the ranking",
    )
    started_at: datetime = Field(description="Start of the trial, UTC")
    ended_at: datetime | None = Field(default=None, description="End of the trial, UTC")

    @property
    def only_case(self) -> TrialCase | None:
        """Return what the trial gave in its one case, ``None`` when it names several or none."""
        return next(iter(self.cases.values())) if len(self.cases) == 1 else None


def trials_path(session_dir: str | Path) -> Path:
    """Return ``<session>/trials.jsonl``."""
    return Path(session_dir) / SESSION_TRIALS_FILENAME


def append_trial(session_dir: str | Path, line: TrialLine) -> Path:
    """Append one line to the journal, in one write, and return its path."""
    target = trials_path(session_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dump_stored(line), ensure_ascii=False) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return target


def cut_remnant(session_dir: str | Path) -> bool:
    """Drop the text after the last newline of the journal, return whether there was any.

    That text is the remnant of a write a crash cut. It is never a trial, and
    the next append would glue a new line to it and make both unreadable.
    """
    target = trials_path(session_dir)
    if not target.is_file():
        return False
    data = target.read_bytes()
    kept = data[: data.rfind(b"\n") + 1]
    if len(kept) == len(data):
        return False
    with open(target, "r+b") as handle:
        handle.truncate(len(kept))
    return True


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
        line = read_stored(
            TrialLine, check_sealed(payload, TRIAL_VERSIONS, path=target, line=number)
        )
        latest[line.trial] = line
    return [latest[number] for number in sorted(latest)]


def next_trial_number(session_dir: str | Path) -> int:
    """Return the number the next trial takes: one above the highest journaled."""
    trials = read_trials(session_dir)
    return 1 if not trials else trials[-1].trial + 1


def physical_parameters(line: TrialLine) -> dict[str, float]:
    """Return the physical value of each parameter of a trial."""
    return {name: param.value for name, param in line.params.items()}


def trial_rows(line: TrialLine) -> Iterator[dict[str, Any]]:
    """Yield one plain row per case of a trial: what the promotion, the report and figures read.

    ``cost`` is the number the search minimised and ``case_cost`` the cost of the
    case of the row; ``status`` and ``case_status`` go the same way. A line that
    names no case gives one row with a null ``case_id``.
    ``duration_s`` is the time between the two stamps of the line.
    """
    duration = (line.ended_at - line.started_at).total_seconds() if line.ended_at else 0.0
    cases: dict[str | None, TrialCase | None] = dict(line.cases) or {None: None}
    for case_id, case in cases.items():
        yield {
            "phase": line.phase,
            "restart": line.restart,
            "trial": line.trial,
            "case_id": case_id,
            "cost": line.cost,
            "case_cost": None if case is None else case.cost,
            "components": {} if case is None else dict(case.components),
            "parameters": {
                name: param.model_dump(exclude_defaults=True) for name, param in line.params.items()
            },
            "status": line.status,
            "case_status": None if case is None else case.status,
            "from_cache": False if case is None else case.from_cache,
            "params_hash": None if case is None else case.params_hash,
            "sim_id": None if case is None else case.sim_id,
            "rel_dir": None if case is None else case.rel_dir,
            "speculative_unused": line.speculative_unused,
            "duration_s": duration,
        }


__all__ = [
    "TRIAL_SCHEMA",
    "TRIAL_VERSIONS",
    "TrialCase",
    "TrialLine",
    "TrialParam",
    "TrialStatus",
    "append_trial",
    "cut_remnant",
    "next_trial_number",
    "physical_parameters",
    "read_trials",
    "trial_rows",
    "trials_path",
]
