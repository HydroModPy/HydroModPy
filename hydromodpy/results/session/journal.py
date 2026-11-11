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
:data:`TRIAL_SCHEMA` and one event of :data:`TRIAL_EVENTS`. A trial is written
once when the optimizer asks for it (``proposed``), once when its cost is known
(``finished``) and once more when it becomes a run (``linked``). Each line is
the whole trial as it is known at that instant, so the reader keeps one line
per trial number: the highest event, then the last line of the file. What a
trial gave in each case sits under ``cases``, keyed by ``case_id``. ``cost`` is
the number the search minimized, null on a failed trial, on a proposed one or
when the search keeps no single cost. A trial with only its ``proposed`` line
was cut by a stop: it reads ``running``, without a cost. A ``hydromodpy.trial.v2``
line, written by 2.0, reads as a ``finished`` line without the fields v3 added.
A trailing line without its newline is the remnant of a crash and is ignored;
any other unreadable line is an error.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary, dump_stored, read_stored
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import SESSION_TRIALS_FILENAME
from hydromodpy.results.storage.json_io import check_sealed
from hydromodpy.results.storage.run_profile import ProfileLine
from hydromodpy.schema.changes import prerelease_refusal

TRIAL_SCHEMA: Final[str] = "hydromodpy.trial.v3"
"""Schema id of one line of ``trials.jsonl``."""

_PRERELEASE_SCHEMA: Final[str] = "hydromodpy.trial.v1"
"""Schema id only a pre-release of 2.0 wrote, refused by name."""

TRIAL_EVENTS: Final[dict[str, int]] = {"proposed": 0, "finished": 1, "linked": 2}
"""The events of a trial and their rank: the reader keeps the highest one."""

TrialEvent = Annotated[str, Vocabulary(*TRIAL_EVENTS)]
"""What a line of the journal records: the trial asked for, scored or made a run."""

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


BOUND_TOLERANCE: Final[float] = 1e-6
"""Share of the searched range within which a value counts as on its bound."""


def on_bound(payload: Any) -> bool:
    """Whether a journaled parameter ended on a bound of its searched range.

    Read in the space the search moved in (``transformed_*``), where the
    range is the one the optimizer saw; a bare value carries no bounds.
    """
    if isinstance(payload, TrialParam):
        payload = payload.model_dump(exclude_defaults=True)
    if not isinstance(payload, Mapping):
        return False
    value, bounds = payload.get("transformed_value"), payload.get("transformed_bounds")
    if value is None or not bounds:
        value, bounds = payload.get("value"), payload.get("bounds")
    if value is None or not bounds or len(bounds) != 2:
        return False
    lower, upper = float(bounds[0]), float(bounds[1])
    margin = BOUND_TOLERANCE * abs(upper - lower)
    return abs(float(value) - lower) <= margin or abs(float(value) - upper) <= margin


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
    rule: str | None = Field(
        default=None,
        description="Version of the scoring rule the cost was computed under, null on a 2.0 line",
    )
    window: str | None = Field(
        default=None,
        description="Name of the scored period of role calibration, null on a 2.0 line",
    )

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str | None) -> str | None:
        return None if value is None else checked_rel_dir(value)


class TrialLine(HydroModelBase):
    """One event of one trial, one line of the journal: the whole trial as known then."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=TRIAL_SCHEMA, alias="schema", description="Schema id")
    event: TrialEvent = Field(
        default="finished",
        description="proposed when the optimizer asks, finished when the cost is known, "
        "linked when the trial became a run. A 2.0 line has none and reads as finished",
    )
    trial: int = Field(ge=1, description="Trial number, unique in the session")
    phase: str = Field(description="Phase the trial belongs to")
    restart: int = Field(default=0, ge=0, description="Restart of that phase")
    batch: int | None = Field(
        default=None,
        ge=1,
        description="Rank of the optimizer call that proposed the trial in its phase and "
        "restart, from 1. Null on a 2.0 line",
    )
    proposed_at: datetime | None = Field(
        default=None, description="When the optimizer proposed the trial, UTC"
    )
    params: dict[str, TrialParam] = Field(
        default_factory=dict, description="Values the search proposed, by parameter"
    )
    cost: float | None = Field(
        default=None,
        description="The number the search minimized, null for a failed trial or when the "
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
    started_at: datetime | None = Field(
        default=None, description="Start of the trial, UTC, null on a proposed line"
    )
    ended_at: datetime | None = Field(default=None, description="End of the trial, UTC")
    profile: list[ProfileLine] = Field(
        default_factory=list,
        description="Where the time of the trial went, in the form of the lines of "
        "profile.json: one step line per step the trial played, one solve line per run of "
        "its plan, reused = rerun when the run was rerun from the previous trial of its "
        "lane. Empty for a trial read from the cost cache",
    )

    @model_validator(mode="after")
    def _linked_names_its_case(self) -> TrialLine:
        if self.event == "linked" and not self.cases:
            raise ValueError(
                f"trial {self.trial} is linked to a run and names no case: a linked line "
                "carries the case of the run it became."
            )
        return self

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
    """Return the trials of a session, one per number.

    Of the lines of one number the highest event wins (``linked``, then
    ``finished``, then ``proposed``), and the last line of the file at an equal
    rank. The writer puts ``proposed`` before ``finished`` and ``linked`` after,
    so this keeps the same lines as the last line of each number would.
    """
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
        line = _read_line(payload, target, number)
        held = latest.get(line.trial)
        if held is None or TRIAL_EVENTS[line.event] >= TRIAL_EVENTS[held.event]:
            latest[line.trial] = line
    return [latest[number] for number in sorted(latest)]


def _read_line(payload: Any, target: Path, number: int) -> TrialLine:
    """Return one line of the journal; refuse a pre-release line and an unknown event."""
    if isinstance(payload, dict) and payload.get("schema") == _PRERELEASE_SCHEMA:
        where = f"{target}:{number}"
        raise SchemaVersionMismatchError(
            prerelease_refusal(where, [f"schema = {_PRERELEASE_SCHEMA!r}"], rewritable=False),
            document=where,
            found=_PRERELEASE_SCHEMA,
            expected=TRIAL_SCHEMA,
        )
    line = read_stored(TrialLine, check_sealed(payload, TRIAL_VERSIONS, path=target, line=number))
    if line.event not in TRIAL_EVENTS:
        raise ValueError(
            f"{target}:{number} records the event {line.event!r}; a trial line records one of "
            f"{', '.join(TRIAL_EVENTS)}."
        )
    return line


def next_trial_number(session_dir: str | Path) -> int:
    """Return the number the next trial takes: one above the highest journaled, proposed included."""
    trials = read_trials(session_dir)
    return 1 if not trials else trials[-1].trial + 1


def physical_parameters(line: TrialLine) -> dict[str, float]:
    """Return the physical value of each parameter of a trial."""
    return {name: param.value for name, param in line.params.items()}


def trial_rows(line: TrialLine) -> Iterator[dict[str, Any]]:
    """Yield one plain row per case of a trial: what the promotion, the report and figures read.

    ``cost`` is the number the search minimized and ``case_cost`` the cost of the
    case of the row; ``status`` and ``case_status`` go the same way. A line that
    names no case gives one row with a null ``case_id``.
    ``duration_s`` is the time between the two stamps of the line. ``batch`` is
    the optimizer call that proposed the trial, ``rule`` and ``window`` say how
    and on which period the case was scored, ``solve_s`` is the sum of the solve
    lines of the profile and ``reused`` is ``rerun`` when one run of the trial was
    rerun from its lane, ``no`` when every run was built. The three are null on a
    trial without a solve line, a cached one or a 2.0 line.
    """
    duration = (
        (line.ended_at - line.started_at).total_seconds()
        if line.ended_at and line.started_at
        else 0.0
    )
    solves = [entry for entry in line.profile if entry.kind == "solve"]
    solve_s = sum(entry.duration_s or 0.0 for entry in solves) if solves else None
    reused = None
    if solves:
        reused = "rerun" if any(entry.reused == "rerun" for entry in solves) else "no"
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
            "batch": line.batch,
            "rule": None if case is None else case.rule,
            "window": None if case is None else case.window,
            "solve_s": solve_s,
            "reused": reused,
        }


__all__ = [
    "BOUND_TOLERANCE",
    "TRIAL_EVENTS",
    "TRIAL_SCHEMA",
    "TRIAL_VERSIONS",
    "TrialCase",
    "TrialEvent",
    "TrialLine",
    "TrialParam",
    "TrialStatus",
    "append_trial",
    "cut_remnant",
    "next_trial_number",
    "on_bound",
    "physical_parameters",
    "read_trials",
    "trial_rows",
    "trials_path",
]
