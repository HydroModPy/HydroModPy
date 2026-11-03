"""The descriptor of one phase of a staged search: ``phases/<phase>/session.json``.

Why
---
A staged calibration freezes what an earlier phase found and searches the
rest. A resumed session reuses a phase that completed with the same frozen
values, so each phase states its status, what it froze and from where, its
best trial and how many times it restarted. A phase has no journal of its
own: its trials are the lines of the session journal carrying its name.

Format
------
See :class:`PhaseDescriptor`, schema id :data:`PHASE_SCHEMA`. ``frozen`` maps a parameter to its value and
names the phase it came from, as in ``{"K": 6.1e-6, "from": "steady_k"}``.
``stop_state`` and ``stopping_rule`` say why the search of the phase stopped,
and ``stop_note`` says when the phase froze the best of a budget-only search;
a phase written before they existed reads without them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import dump_stored, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.checks import StopState
from hydromodpy.results.session.descriptor import BestTrial, SessionStatus
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME, SESSION_PHASES_DIRNAME
from hydromodpy.results.storage.json_io import read_sealed_json, write_json_durable

PHASE_SCHEMA: Final[str] = "hydromodpy.phase.v1"
"""Schema id of ``phases/<phase>/session.json``."""

PHASE_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.phase.v1", current=PHASE_SCHEMA
)
"""Versions of the document this code reads."""


class PhaseDescriptor(HydroModelBase):
    """Status, frozen values and best trial of one phase."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PHASE_SCHEMA, alias="schema", description="Schema id")
    phase_id: str = Field(description="Id of the phase, unique in the session")
    name: str = Field(pattern=r"^[A-Za-z0-9_]+$", description="Name of the phase, its directory")
    index: int = Field(ge=0, description="Rank of the phase in the chain")
    status: SessionStatus = Field(default="running")
    frozen: dict[str, Any] = Field(
        default_factory=dict, description="Values frozen from earlier phases"
    )
    best: BestTrial | None = Field(default=None, description="Best trial of the phase")
    restarts: int = Field(default=0, ge=0, description="Times the phase restarted")
    stop_state: StopState | None = Field(
        default=None,
        description="Why the search of the phase stopped: rule_met, plan_exhausted or "
        "budget_spent; none until it closes",
    )
    stopping_rule: str | None = Field(
        default=None,
        description="The rule that search stops on, 'budget' for one with no rule of its own",
    )
    stop_note: str | None = Field(
        default=None,
        description="'froze the best of a budget-only search' when the phase passed on "
        "the best trial of a search with no rule of its own; none otherwise",
    )


def phases_dir(session_dir: str | Path) -> Path:
    """Return ``<session>/phases``."""
    return Path(session_dir) / SESSION_PHASES_DIRNAME


def phase_dir(session_dir: str | Path, name: str) -> Path:
    """Return ``<session>/phases/<name>``."""
    return phases_dir(session_dir) / name


def write_phase(session_dir: str | Path, descriptor: PhaseDescriptor) -> Path:
    """Write the descriptor of a phase durably and return its path."""
    target = phase_dir(session_dir, descriptor.name) / SESSION_DESCRIPTOR_FILENAME
    return write_json_durable(target, dump_stored(descriptor))


def read_phase(session_dir: str | Path, name: str) -> PhaseDescriptor:
    """Read the descriptor of one phase."""
    return read_stored(
        PhaseDescriptor,
        read_sealed_json(
            phase_dir(session_dir, name) / SESSION_DESCRIPTOR_FILENAME, PHASE_VERSIONS
        ),
    )


def list_phases(session_dir: str | Path) -> list[PhaseDescriptor]:
    """Return every phase of a session, by index."""
    root = phases_dir(session_dir)
    if not root.is_dir():
        return []
    found = [
        read_phase(session_dir, entry.name)
        for entry in root.iterdir()
        if (entry / SESSION_DESCRIPTOR_FILENAME).is_file()
    ]
    return sorted(found, key=lambda phase: phase.index)


__all__ = [
    "PHASE_SCHEMA",
    "PHASE_VERSIONS",
    "PhaseDescriptor",
    "list_phases",
    "phase_dir",
    "phases_dir",
    "read_phase",
    "write_phase",
]
