"""What a run keeps of its solver outputs, and the witness of a purged trial.

The level of a run is read from its lineage, never written. The three levels,
lowest first::

    LEVELS = ("research", "result", "publication")

``level_of`` gives ``research`` for a kept calibration trial
(``kind = "trial"``), ``publication`` for a copy that carries
``PUBLICATION.json``, and ``result`` for every other run. What each level
keeps is the table of the architecture (ARCH 5)::

    kept                                research   result   publication
    log line, series at scored points   yes        n/a      n/a
    end-of-period head, compact         if kept    yes      yes
    per-cell budget                     criterion  all      all
    final state in float64              yes        yes      yes
    tables, seal, inputs by digest      yes        yes      yes
    figures and exports                 no         dated    at the copy
    bytes of inputs, image digest       no         no       by default
    face flows, solver files            no         on demand on demand

The module is not named ``retention.py`` because ``results/retention.py`` is
the collection behind ``hmp catalog gc``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.io.document_version import check_document
from hydromodpy.results.storage.contract import PURGEABLE_TRIAL_ENTRIES, RUN_PURGED_FILENAME
from hydromodpy.results.storage.json_io import read_json, write_json_durable
from hydromodpy.schema.lineage import Lineage

LEVELS: tuple[str, ...] = ("research", "result", "publication")
"""The levels of a run, from the lightest to the most complete."""

PURGED_SCHEMA: Final[str] = "hydromodpy.purged.v1"
"""Schema id of ``purged.json``, the witness ``gc`` leaves on a kept trial."""

_PUBLICATION_REFUSAL = (
    "a run is written at the research or the result level; a published copy is made by hmp publish"
)


def _rank(level: str) -> int:
    """Return where a level stands, and refuse a word that is not one."""
    try:
        return LEVELS.index(level)
    except ValueError:
        raise ValueError(f"A run level is one of {', '.join(LEVELS)}; got {level!r}.") from None


def level_of(lineage: Lineage | None, *, published: bool = False) -> str:
    """Return the level of a run, from its lineage and from its published copy.

    ``published`` is true when the directory carries ``PUBLICATION.json``. A
    kept calibration trial is ``research``. Every other run is ``result``:
    ``promoted``, ``rerun``, ``version``, ``replay`` and a run with no lineage.
    """
    if published:
        return "publication"
    if lineage is not None and lineage.kind == "trial":
        return "research"
    return "result"


def at_least(level: str, wanted: str) -> bool:
    """Return whether ``level`` is ``wanted`` or more complete."""
    return _rank(level) >= _rank(wanted)


def renders(level: str) -> bool:
    """Return whether a run of ``level`` draws figures and writes its exports."""
    return _rank(level) >= _rank("result")


@dataclass(frozen=True, slots=True)
class Retention:
    """What one run keeps: its level, its per-cell budget, its raw files and face flows.

    ``level`` is read by :func:`level_of`. ``budget`` is the ``BudgetKeep`` the
    planning decided for the run. ``solver_files`` is ``keep_solver_files`` and
    ``face_flows`` is ``keep_face_flows``: a ``research`` run keeps neither,
    whatever the configuration asks.
    """

    level: str
    budget: BudgetKeep
    solver_files: bool = False
    face_flows: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.level, str):
            raise TypeError(f"Retention.level is a str, got {type(self.level).__name__}.")
        if self.level == "publication":
            raise ValueError(_PUBLICATION_REFUSAL)
        _rank(self.level)
        if not isinstance(self.budget, BudgetKeep):
            raise TypeError(f"Retention.budget is a BudgetKeep, got {type(self.budget).__name__}.")
        if not isinstance(self.solver_files, bool):
            raise TypeError(
                f"Retention.solver_files is a bool, got {type(self.solver_files).__name__}."
            )
        if not isinstance(self.face_flows, bool):
            raise TypeError(
                f"Retention.face_flows is a bool, got {type(self.face_flows).__name__}."
            )

    @classmethod
    def of(cls, level: str, results: Any, budget: BudgetKeep) -> Retention:
        """Return what a run of ``level`` keeps, from its ``[simulation.results]``.

        ``results`` is the ``ResultsConfig`` of the run, read for
        ``keep_solver_files`` and ``keep_face_flows``. ``budget`` is the
        ``BudgetKeep`` the planning derived from ``keep_per_cell_budget``, or
        the one a resume read back from the store. A ``research`` run keeps
        neither the raw solver files nor the face flows.
        """
        if level == "publication":
            raise ValueError(_PUBLICATION_REFUSAL)
        _rank(level)
        research = level == "research"
        return cls(
            level=level,
            budget=budget,
            solver_files=False if research else bool(results.keep_solver_files),
            face_flows=False if research else bool(results.keep_face_flows),
        )


class Purged(HydroModelBase):
    """What ``gc`` removed from one kept trial, and when.

    It lives outside the seal, since the seal is immutable. ``entries`` maps a
    relative path of the trial directory to the bytes removed there, and names
    only what :data:`PURGEABLE_TRIAL_ENTRIES` allows.
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PURGED_SCHEMA, alias="schema", description="Schema id")
    at: datetime = Field(description="Instant gc removed the entries, UTC")
    entries: dict[str, int] = Field(
        default_factory=dict, description="Relative path of each removed entry to its bytes"
    )

    @model_validator(mode="after")
    def _names_only_what_gc_removes(self) -> Purged:
        refused = sorted(set(self.entries) - PURGEABLE_TRIAL_ENTRIES)
        if refused:
            raise ValueError(
                f"names {refused[0]!r}, which gc never removes; gc removes "
                f"only {', '.join(sorted(PURGEABLE_TRIAL_ENTRIES))}."
            )
        return self


def purged_path(run_dir: str | Path) -> Path:
    """Return ``<run>/purged.json``."""
    return Path(run_dir) / RUN_PURGED_FILENAME


def read_purged(run_dir: str | Path) -> Purged | None:
    """Return the purge witness of a run, or ``None`` when it carries none.

    A witness of another schema is refused by the schema it names. Its entries
    are refused when they name anything gc does not remove.
    """
    path = purged_path(run_dir)
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return None
    check_document(
        payload,
        PURGED_SCHEMA,
        document=path,
        key="schema",
        remedy=f"A purge witness is {PURGED_SCHEMA!r}.",
    )
    return read_stored(Purged, payload)


def write_purged(run_dir: str | Path, purged: Purged) -> Path:
    """Write the witness durably, before anything is removed, and return its path."""
    path = purged_path(run_dir)
    write_json_durable(path, purged.model_dump(mode="json", by_alias=True))
    return path


__all__ = [
    "LEVELS",
    "PURGED_SCHEMA",
    "Purged",
    "Retention",
    "at_least",
    "level_of",
    "purged_path",
    "read_purged",
    "renders",
    "write_purged",
]
