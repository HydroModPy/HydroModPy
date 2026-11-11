"""The issue of an attempt: ``outcome.json``, and the status a reader derives.

Why
---
A run directory exists before anything is computed and stays when the
attempt dies. What happened to it has to be readable from the directory
alone: by the launcher that spawned the worker, by ``hmp ls --plan``,
by the indexer. ``outcome.json`` is written at the creation of the
directory, before the first pipeline step, and rewritten at every exit,
SIGTERM included. When the worker dies without writing (a Fortran stop, an
OOM kill, a walltime), the parent writes ``failed`` in its place and says so
in ``written_by``.

Format
------
See :class:`Outcome`. ``status`` is what the writer knew; ``exit_code`` and
``signal`` are what the process ended with; ``log_tail`` is the end of the
run log, so a failed case explains itself from its own directory.
``request_id`` is written once the inputs of the attempt are resolved
(:mod:`hydromodpy.results.record.request_identity`); the next attempt compares it
before it resumes.

Precedence, when reading
------------------------
:func:`effective_status` reads the directory and answers one word. The seal
wins: ``manifest.json`` present means ``completed`` whatever the outcome says,
because the manifest is written before the outcome flips to ``completed``, and
the outcome is not even read. A seal this code cannot read, or the outcome or
the pulse of an unsealed directory, is ``unreadable``, after one warning naming
it: a directory of another version never stops a listing.
Then the outcome: ``completed`` without a manifest is ``partial`` (the seal
never landed); ``failed`` and ``aborted`` stand; ``running`` is ``running``
while the pulse is fresh and ``stale`` once it is older than the threshold
the caller passes, or at once when its death is proven (this host, process
gone: an OOM kill writes nothing). No outcome at all is ``unknown``.
``stale`` is a word for a display, never an authorization.

This precedence is for a run directory only. A session directory has no
manifest: its status is ``read_session(dir).status``, read from its
``session.json`` (:mod:`hydromodpy.results.session.descriptor`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary, dump_stored, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.pipeline_steps import STEP_NAMES
from hydromodpy.core.state.host import death_is_proven
from hydromodpy.results.heartbeat import heartbeat_age_s
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME
from hydromodpy.results.storage.json_io import (
    UNREADABLE_ERRORS,
    read_sealed_json,
    readable,
    warn_unreadable,
    write_json_durable,
)

OUTCOME_SCHEMA: Final[str] = "hydromodpy.outcome.v1"
"""Schema id of the document."""

OUTCOME_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.outcome.v1", current=OUTCOME_SCHEMA
)
"""Versions of the document this code reads."""

DEFAULT_STALE_AFTER_S: Final[float] = 300.0
"""Age of the pulse past which a running attempt reads as stale."""

OutcomeStatus = Annotated[str, Vocabulary("running", "completed", "failed", "aborted")]
"""What the writer of the outcome knew when it wrote."""

WrittenBy = Annotated[str, Vocabulary("worker", "launcher", "trap")]
"""Who wrote the outcome: the attempt itself, its parent, or a shell trap."""

EffectiveStatus = Literal[
    "running", "completed", "partial", "failed", "aborted", "stale", "unknown", "unreadable"
]
"""What a reader concludes from the directory."""


class OutcomeError(HydroModelBase):
    """The error that ended an attempt."""

    type: str = Field(description="Exception class or signal name")
    message: str = Field(description="What it said")


class Outcome(HydroModelBase):
    """The issue of one attempt of a run or a session."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=OUTCOME_SCHEMA, alias="schema", description="Schema id")
    case_id: str = Field(description="Case the directory is")
    site: str | None = Field(default=None, description="Site of the case")
    project: str | None = Field(default=None, description="Project of the case")
    attempt: int = Field(ge=1, description="Attempt number, 1 for the first")
    attempt_id: str = Field(description="Id of the attempt, minted at entry")
    sim_id: str | None = Field(default=None, description="Id of the run once it has one")
    request_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "What the attempt asks for, the sha256 of its request once its inputs are resolved. "
            "Absent before then, and in an outcome written before this field existed."
        ),
    )
    status: OutcomeStatus = Field(description="What the writer knew")
    exit_code: int | None = Field(default=None, description="Exit code of the process, at exit")
    signal: int | None = Field(default=None, description="Signal that ended the process, if one")
    written_by: WrittenBy = Field(description="Who wrote this document")
    started_at: datetime = Field(description="Entry of the attempt, UTC")
    ended_at: datetime | None = Field(default=None, description="Exit of the attempt, UTC")
    host: str = Field(description="Host of the attempt")
    pid: int = Field(description="Process of the attempt")
    scheduler_job_id: str | None = Field(default=None, description="Scheduler job, on a cluster")
    step: str | None = Field(
        default=None,
        description=(
            "Pipeline step reached. An open vocabulary: x-hmp-vocabulary holds the steps of a "
            "simulation today, a later version may add one, and a reader keeps a name it does "
            "not know."
        ),
        json_schema_extra={"x-hmp-vocabulary": list(STEP_NAMES), "x-hmp-vocabulary-open": True},
    )
    error: OutcomeError | None = Field(default=None, description="What ended a failed attempt")
    log_tail: list[str] = Field(default_factory=list, description="Last lines of the run log")

    @model_validator(mode="after")
    def _consistent(self) -> Outcome:
        if not OUTCOME_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {OUTCOME_SCHEMA!r}")
        if self.status == "running" and self.ended_at is not None:
            raise ValueError("a running attempt has no ended_at")
        if self.status != "running" and self.ended_at is None:
            raise ValueError(f"a {self.status} attempt carries its ended_at")
        if self.status == "completed" and self.error is not None:
            raise ValueError("a completed attempt carries no error")
        return self


def outcome_path(run_dir: str | Path) -> Path:
    """Return ``<dir>/outcome.json``."""
    return Path(run_dir) / RUN_OUTCOME_FILENAME


def write_outcome(run_dir: str | Path, outcome: Outcome) -> Path:
    """Write the outcome durably and return its path."""
    return write_json_durable(outcome_path(run_dir), dump_stored(outcome))


def read_outcome(run_dir: str | Path) -> Outcome | None:
    """Return the outcome of a directory, or ``None`` when it has none."""
    try:
        payload = read_sealed_json(outcome_path(run_dir), OUTCOME_VERSIONS)
    except FileNotFoundError:
        return None
    return read_stored(Outcome, payload)


def effective_status(
    run_dir: str | Path,
    *,
    now: datetime | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> EffectiveStatus:
    """Return what a run directory says happened, by the precedence of the module docstring.

    For a run directory only. The status of a session is
    ``read_session(session_dir).status``, read from its ``session.json``.
    """
    directory = Path(run_dir)
    if (directory / RUN_MANIFEST_FILENAME).is_file():
        return "unreadable" if readable(read_seal, directory) is None else "completed"
    try:
        outcome = read_outcome(directory)
    except UNREADABLE_ERRORS as exc:
        warn_unreadable(directory, exc)
        return "unreadable"
    if outcome is None:
        return "unknown"
    if outcome.status == "completed":
        return "partial"
    if outcome.status in ("failed", "aborted"):
        return outcome.status
    if death_is_proven(outcome.host, outcome.pid):
        return "stale"
    instant = now if now is not None else datetime.now(UTC)
    try:
        age = heartbeat_age_s(directory, instant)
    except UNREADABLE_ERRORS as exc:
        warn_unreadable(directory, exc)
        return "unreadable"
    if age is None:
        pulse = datetime.fromtimestamp(outcome_path(directory).stat().st_mtime, tz=UTC)
        age = (instant - pulse).total_seconds()
    return "stale" if age > stale_after_s else "running"


__all__ = [
    "DEFAULT_STALE_AFTER_S",
    "OUTCOME_SCHEMA",
    "OUTCOME_VERSIONS",
    "EffectiveStatus",
    "Outcome",
    "OutcomeError",
    "OutcomeStatus",
    "WrittenBy",
    "effective_status",
    "outcome_path",
    "read_outcome",
    "write_outcome",
]
