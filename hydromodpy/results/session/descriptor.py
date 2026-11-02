"""The descriptor of a calibration session: ``sessions/<case>/session.json``.

Why
---
A calibration is expensive, and what it found has to be readable without
the index and without the calibration code: which site, which case, which
configuration (its hash; the frozen file sits next to it), which search,
which trial won, and whether the search finished. The descriptor is written
before the first trial, rewritten at every change of status, and rewritten
in under a second on SIGTERM with the best trial so far, so an interrupted
session still points at something.

Format
------
See :class:`SessionDescriptor`. ``best`` names the winning trial by number
and, once promoted, by the ``sim_id`` and directory of the run. ``status`` is
``completed`` when the search met its rule, exhausted its plan, or spent the
budget of a search with no rule of its own; ``partial`` when the budget ran
out before a rule the engine has, or when the promotion of its best trial
failed; ``aborted`` on a signal; ``failed`` on an error of the search itself.
A session whose search completed is never written ``failed`` for what
happened after it. ``stop_state`` says which of the three ways the search
of the phase whose best the session holds stopped
(:data:`~hydromodpy.results.checks.StopState`), and ``stop_note`` names the
phases of a staged session that froze the best of a budget-only search. A
session written before they existed reads without them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary, read_stored
from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.state.paths import parse_rel_dir, session_dir_rel, sessions_dir_for
from hydromodpy.results.checks import StopState
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME
from hydromodpy.results.storage.json_io import (
    read_sealed_json,
    readable_documents,
    write_json_durable,
)

SESSION_SCHEMA: Final[str] = "hydromodpy.session.v3"
"""Schema id of the descriptor."""

SESSION_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.session.v3", current=SESSION_SCHEMA
)
"""Versions of the descriptor this code reads."""

SessionStatus = Annotated[str, Vocabulary("running", "completed", "partial", "aborted", "failed")]
"""Where a session or a phase stands."""


class BestTrial(HydroModelBase):
    """The trial a session or a phase holds as its best."""

    trial: int = Field(ge=1, description="Trial number, unique in the session")
    sim_id: str | None = Field(default=None, description="Run of the promoted trial")
    rel_dir: str | None = Field(default=None, description="Directory of that run, a hint")
    objective: float | None = Field(default=None, description="Objective value of the trial")

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str | None) -> str | None:
        return None if value is None else checked_rel_dir(value)


class ScoredSamples(HydroModelBase):
    """The pairs one dated output's cost was scored on.

    A stamp closes its period, so ``first`` and ``last`` are the ends of the
    first and last period scored, not the bounds of a window.
    """

    n: int = Field(ge=0, description="Number of paired samples scored")
    n_sim_nan: int | None = Field(
        default=None,
        ge=0,
        description="Pairs of the window dropped because the simulated value is NaN "
        "(a dry cell); null when not counted",
    )
    first: date | None = Field(default=None, description="First period-end stamp scored")
    last: date | None = Field(default=None, description="Last period-end stamp scored")


def scored_samples_text(samples: Mapping[str, ScoredSamples]) -> str:
    """Return the pairs of each output in words, one clause per output.

    A stamp closes its period, so the dates are the ends of the first and
    last period scored.
    """
    clauses = []
    for name, scored in samples.items():
        clause = f"{name} {scored.n} pair(s)"
        if scored.n_sim_nan:
            clause += f" ({scored.n_sim_nan} lost to a NaN simulated value)"
        if scored.first is not None and scored.last is not None:
            clause += f", period ends {scored.first.isoformat()} to {scored.last.isoformat()}"
        clauses.append(clause)
    return "; ".join(clauses)


class SessionDescriptor(HydroModelBase):
    """Identity, search and outcome of one calibration session."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=SESSION_SCHEMA, alias="schema", description="Schema id")
    site: str | None = Field(default=None, description="Site of the case")
    session_id: str = Field(description="Id of the session")
    case_id: str = Field(description="Case the session calibrates")
    config_hash: str = Field(description="Identity hash of the resolved case configuration")
    hydromodpy_version: str = Field(description="Version that ran the session")
    method: str = Field(description="Search method")
    search_space: dict[str, Any] = Field(default_factory=dict, description="Parameter to bounds")
    objective_name: str = Field(description="Objective the search minimised")
    objective_label: str | None = Field(
        default=None,
        description=(
            "What the objective value is, read as a cost: '1 - nse_log' for an "
            "efficiency, 'log10(rmse)' for a transformed block"
        ),
    )
    objective_window: DateWindow | None = Field(
        default=None,
        description=(
            "Window the objective was scored on, as declared, a bound left open "
            "closed by the dates of [simulation.time]"
        ),
    )
    objective_samples: dict[str, ScoredSamples] = Field(
        default_factory=dict,
        description=(
            "Per dated output, the pairs the cost of the best trial was scored on; "
            "empty when no pair was counted"
        ),
    )
    best: BestTrial | None = Field(default=None, description="Best trial so far")
    status: SessionStatus = Field(default="running")
    started_at: datetime = Field(description="Start of the session, UTC")
    ended_at: datetime | None = Field(default=None, description="End of the session, UTC")
    error_message: str | None = Field(default=None, description="Why a failed session failed")
    root_search: dict[str, Any] | None = Field(
        default=None, description="Bracket or roots a root search closed with"
    )
    stop_state: StopState | None = Field(
        default=None,
        description="Why the search stopped: rule_met, plan_exhausted or budget_spent; "
        "for a staged session, the search of the last phase; none until it closes",
    )
    stopping_rule: str | None = Field(
        default=None,
        description="The rule that search stops on, 'budget' for one with no rule of its own",
    )
    stop_note: str | None = Field(
        default=None,
        description="The phases that froze the best of a budget-only search, in words; "
        "none when no phase did",
    )

    @model_validator(mode="after")
    def _consistent(self) -> SessionDescriptor:
        if not SESSION_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {SESSION_SCHEMA!r}")
        if self.status == "running" and self.ended_at is not None:
            raise ValueError("a running session has no ended_at")
        return self


def session_descriptor_path(session_dir: str | Path) -> Path:
    """Return ``<session>/session.json``."""
    return Path(session_dir) / SESSION_DESCRIPTOR_FILENAME


def write_session(session_dir: str | Path, descriptor: SessionDescriptor) -> Path:
    """Write the descriptor durably and return its path."""
    return write_json_durable(
        session_descriptor_path(session_dir), descriptor.model_dump(mode="json", by_alias=True)
    )


def read_session(session_dir: str | Path) -> SessionDescriptor:
    """Read the descriptor of a session directory."""
    return read_stored(
        SessionDescriptor, read_sealed_json(session_descriptor_path(session_dir), SESSION_VERSIONS)
    )


def list_session_dirs(project_root: str | Path) -> list[Path]:
    """Return every session directory of a project, by name.

    A directory under ``sessions/`` without a ``session.json`` is not a
    calibration session and is left out.
    """
    root = sessions_dir_for(Path(project_root))
    if not root.is_dir():
        return []
    return sorted(entry for entry in root.iterdir() if session_descriptor_path(entry).is_file())


def find_session_dir(project_root: str | Path, session_id: str) -> Path | None:
    """Return the directory of the session whose descriptor carries *session_id*."""
    wanted = str(session_id).replace("-", "").lower()
    for directory, descriptor in readable_documents(read_session, list_session_dirs(project_root)):
        if descriptor.session_id.replace("-", "").lower() == wanted:
            return directory
    return None


def resolve_session_dir(project_root: str | Path, reference: str | None) -> Path:
    """Return the session directory a reference names.

    ``reference`` is ``<case>[.vN]`` or ``sessions/<case>[.vN]``, the exact
    name of one session. ``None`` selects the session that started last among
    those this code reads. A reference that names no session is refused with
    the sessions the project holds.
    """
    root = Path(project_root).expanduser().resolve()
    sessions = list_session_dirs(root)
    if reference is None:
        started = {
            directory: descriptor.started_at
            for directory, descriptor in readable_documents(read_session, sessions)
        }
        if not started:
            raise ConfigMissingError(
                f"No readable calibration session under {sessions_dir_for(root)}."
            )
        return max(started, key=lambda directory: started[directory])
    rel = reference if "/" in reference else session_dir_rel(reference)
    parsed = parse_rel_dir(rel)
    if parsed.kind != "session":
        raise ConfigMissingError(
            f"{reference!r} is not a session: write <case> or {session_dir_rel('<case>')}."
        )
    directory = root / rel
    if directory not in sessions:
        names = ", ".join(entry.name for entry in sessions) or "none"
        raise ConfigMissingError(
            f"No calibration session {reference!r} under {sessions_dir_for(root)}: {names}."
        )
    return directory


__all__ = [
    "SESSION_SCHEMA",
    "SESSION_VERSIONS",
    "BestTrial",
    "ScoredSamples",
    "SessionDescriptor",
    "SessionStatus",
    "find_session_dir",
    "list_session_dirs",
    "read_session",
    "resolve_session_dir",
    "scored_samples_text",
    "session_descriptor_path",
    "write_session",
]
