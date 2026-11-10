"""The descriptor of a calibration session: ``sessions/<case>/session.json``.

Why
---
A calibration is expensive, and what it found has to be readable without
the index and without the calibration code: which sites, which cases, which
configuration (its hash; the frozen file sits next to it), which search,
which trial won, and whether the search finished. The descriptor is written
before the first trial, rewritten at every change of status, and rewritten
in under a second on SIGTERM with the best trial so far, so an interrupted
session still points at something.

Format
------
See :class:`SessionDescriptor`. Whatever depends on a case sits in a table
keyed by ``case_id``, one entry for a session of one case. Whatever depends on a
period sits in a table keyed by its name, one entry for a search with one window.
So a reader written today already walks N cases and N periods, and a joint
calibration or a validation period adds keys and no new meaning.

``best`` names the winning trial by number, its parameters, and, once promoted,
the ``sim_id`` and directory of its run in each case. ``status`` is
``completed`` when the search met its rule, exhausted its plan, or spent the
budget of a search with no rule of its own; ``partial`` when the budget ran
out before a rule the engine has, or when the promotion of its best trial
failed; ``aborted`` on a signal; ``failed`` on an error of the search itself.
A session whose search completed is never written ``failed`` for what
happened after it. ``stop_state`` says which of the three ways the search
of the phase whose best the session holds stopped
(:data:`~hydromodpy.results.record.checks.StopState`), and ``stop_note`` names the
phases of a staged session that froze the best of a budget-only search or
closed a root outside its declared bounds.

A check across fields runs at writing only: a read keeps what a later 2.x wrote.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import (
    Vocabulary,
    dump_stored,
    read_stored,
    reading_stored,
)
from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.state.layout import sessions_dir_for
from hydromodpy.core.state.result_dirs import parse_rel_dir, session_dir_rel
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.record.checks import StopState
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME
from hydromodpy.results.storage.json_io import (
    read_sealed_json,
    readable,
    readable_documents,
    write_json_durable,
)

SESSION_SCHEMA: Final[str] = "hydromodpy.session.v4"
"""Schema id of the descriptor."""

SESSION_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.session.v4", current=SESSION_SCHEMA
)
"""Versions of the descriptor this code reads."""

SessionStatus = Annotated[str, Vocabulary("running", "completed", "partial", "aborted", "failed")]
"""Where a session or a phase stands."""


class BestCase(HydroModelBase):
    """What the best trial gave in one case: its run and its cost."""

    sim_id: str | None = Field(default=None, description="Run of the trial in this case")
    rel_dir: str | None = Field(default=None, description="Directory of that run, a hint")
    cost: float | None = Field(default=None, description="Cost of this case at this trial")

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str | None) -> str | None:
        return None if value is None else checked_rel_dir(value)


class BestTrial(HydroModelBase):
    """The trial a session or a phase holds as its best."""

    trial: int = Field(ge=1, description="Trial number, unique in the session")
    cost: float | None = Field(
        default=None,
        description="Cost of the trial, null when the search keeps no single cost",
    )
    parameters: dict[str, float] = Field(
        default_factory=dict,
        description="Physical value of each parameter of the trial, those a phase froze included",
    )
    cases: dict[str, BestCase] = Field(default_factory=dict, description="By case id")


class ScoredSamples(HydroModelBase):
    """The pairs one dated output of one case was scored on, in one period.

    A stamp closes its period, so ``first`` and ``last`` are the ends of the
    first and last period scored, not the bounds of a window.
    """

    window: str = Field(description="Name of the period scored")
    case_id: str = Field(description="Case scored")
    output: str = Field(description="Dated output scored; two cases may use one name")
    n: int = Field(ge=0, description="Number of paired samples scored")
    n_sim_nan: int | None = Field(
        default=None,
        ge=0,
        description="Pairs of the window dropped because the simulated value is NaN "
        "(a dry cell); null when not counted",
    )
    first: date | None = Field(default=None, description="First period-end stamp scored")
    last: date | None = Field(default=None, description="Last period-end stamp scored")


def scored_samples_text(samples: Iterable[ScoredSamples]) -> str:
    """Return the pairs of each output in words, one clause per output.

    A stamp closes its period, so the dates are the ends of the first and
    last period scored.
    """
    clauses = []
    for scored in samples:
        clause = f"{scored.output} {scored.n} pair(s)"
        if scored.n_sim_nan:
            clause += f" ({scored.n_sim_nan} lost to a NaN simulated value)"
        if scored.first is not None and scored.last is not None:
            clause += f", period ends {scored.first.isoformat()} to {scored.last.isoformat()}"
        clauses.append(clause)
    return "; ".join(clauses)


class ParameterBound(HydroModelBase):
    """One dimension a search walks."""

    lower: float = Field(description="Lower physical bound")
    upper: float = Field(description="Upper physical bound")
    search_space: str = Field(description="Space of the search: identity, log or logit")
    units: str | None = Field(default=None, description="Unit of the bounds")
    targets: dict[str, str] = Field(
        default_factory=dict,
        description="Address of the value in each case it touches, by case id; empty for a "
        "parameter that writes nothing itself",
    )


class CostInterval(HydroModelBase):
    """The range the trials could not tell from the best on the cost. Every member is optional."""

    lower: float | None = Field(default=None, description="Low end, in the unit of the parameter")
    upper: float | None = Field(default=None, description="High end, in the unit of the parameter")
    margin: float | None = Field(default=None, description="Width on the cost it was read with")
    kind: str | None = Field(default=None, description="How the margin reads: relative, absolute")
    threshold: float | None = Field(default=None, description="Cost at which it was read")
    n_within: int | None = Field(default=None, ge=0, description="Trials inside the margin")
    n_trials: int | None = Field(default=None, ge=0, description="Trials it was read over")
    lower_end: str | None = Field(default=None, description="crossed, open or bound")
    upper_end: str | None = Field(default=None, description="crossed, open or bound")


class RestartRange(HydroModelBase):
    """Where the restarts of a search landed on one parameter."""

    lowest: float | None = Field(default=None, description="Lowest value of the restarts")
    highest: float | None = Field(default=None, description="Highest value of the restarts")
    values: list[float] = Field(default_factory=list, description="Value of each restart")


class ParameterWidth(HydroModelBase):
    """The width of one calibrated value. Every member is optional, and none changes the value."""

    interval: CostInterval | None = Field(default=None, description="Interval on the cost")
    sigma: float | None = Field(
        default=None, description="Linearized standard deviation, in the unit of the parameter"
    )
    restarts: RestartRange | None = Field(default=None, description="Spread of the restarts")
    correlated: dict[str, float] = Field(
        default_factory=dict, description="Correlation coefficient with other parameters, by name"
    )


class SessionCase(HydroModelBase):
    """One case a session calibrates."""

    site: str | None = Field(default=None, description="Site of the case")
    config_hash: str = Field(description="Identity of the resolved configuration of the case")
    config_file: str = Field(description="Frozen file of the case, relative to the session")
    cost_name: str = Field(description="Name of the cost of this case")
    cost_label: str | None = Field(default=None, description="What the cost of this case reads as")
    context: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="By phase, the fingerprint of each member of the cache context: "
        "a --resume refusal names the one that differs",
    )


class ProtocolDeparture(HydroModelBase):
    """One place a session leaves the publication its protocol cites."""

    key: str = Field(description="The option or the concept that carries the departure")
    here: str = Field(description="What this implementation does")
    paper: str = Field(description="What the publication does")
    value: str | None = Field(default=None, description="The value in force, none without option")
    always: bool = Field(default=False, description="No value of an option brings it back")
    written: bool = Field(
        default=False, description="The file wrote the value, rather than its version"
    )


class SessionProtocol(HydroModelBase):
    """The published method a session follows and where it leaves it."""

    name: str = Field(description="Name of the protocol")
    version: str = Field(description="Version the session ran, the pinned one or the installed one")
    departures: list[ProtocolDeparture] = Field(
        default_factory=list, description="Every departure from the publication in force"
    )


class SessionDescriptor(HydroModelBase):
    """Identity, search and outcome of one calibration session."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=SESSION_SCHEMA, alias="schema", description="Schema id")
    session_id: str = Field(description="Id of the session")
    case_id: str = Field(description="Case of the plan this directory is")
    config_hash: str = Field(description="Identity of the frozen configuration of this directory")
    sites: list[str] = Field(default_factory=list, description="Sites of the cases, sorted")
    cases: dict[str, SessionCase] = Field(description="The calibrated cases, by case id")
    hydromodpy_version: str = Field(description="Version that ran the session")
    method: str = Field(description="Search method")
    bounds: dict[str, ParameterBound] = Field(
        default_factory=dict, description="The dimensions the search walks, by parameter"
    )
    cost_name: str = Field(description="Name of the cost the search minimized")
    cost_label: str | None = Field(
        default=None,
        description=(
            "What the cost value reads as: '1 - nse_log' for an efficiency, "
            "'log10(rmse)' for a transformed block"
        ),
    )
    windows: dict[str, PeriodWindow] = Field(
        default_factory=dict,
        description=(
            "Periods of the search whose best the session holds, by name, a bound left open "
            "closed by the dates of [simulation.time]; empty without dates"
        ),
    )
    scored: list[ScoredSamples] = Field(
        default_factory=list,
        description="The pairs the cost of the best trial was scored on; empty when none counted",
    )
    best: BestTrial | None = Field(
        default=None,
        description="Best trial so far; null when the search keeps no single best",
    )
    widths: dict[str, ParameterWidth] = Field(
        default_factory=dict, description="Width of each calibrated value; empty when none"
    )
    protocol: SessionProtocol | None = Field(
        default=None,
        description="The protocol the session follows; none when it names no protocol",
    )
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
        description="The phases that froze the best of a budget-only search or closed a root "
        "outside the declared bounds, in words; none when no phase did",
    )

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> SessionDescriptor:
        if not SESSION_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {SESSION_SCHEMA!r}")
        if reading_stored(info):
            return self
        if self.status == "running" and self.ended_at is not None:
            raise ValueError("a running session has no ended_at")
        check_case_tables(self.cases, self.windows)
        named = sorted({case.site for case in self.cases.values() if case.site})
        if self.sites != named:
            raise ValueError(f"sites are {self.sites}, the cases name {named}")
        if len(self.cases) == 1:
            _check_one_case(self)
        return self

    @property
    def only_case(self) -> str | None:
        """Return the id of the one case of the session, ``None`` when it has several."""
        return next(iter(self.cases)) if len(self.cases) == 1 else None

    @property
    def only_site(self) -> str | None:
        """Return the site of the one case of the session, ``None`` when it has several."""
        case_id = self.only_case
        return None if case_id is None else self.cases[case_id].site

    @property
    def only_run(self) -> BestCase | None:
        """Return what the best trial gave in the one case, ``None`` when it does not say."""
        case_id = self.only_case
        return None if case_id is None or self.best is None else self.best.cases.get(case_id)


def check_case_tables(cases: Mapping[str, Any], windows: Mapping[str, PeriodWindow]) -> None:
    """Refuse a session with no case, or a period that names only some of them."""
    if not cases:
        raise ValueError("a session calibrates at least one case")
    for name, window in windows.items():
        if window.by_case and set(window.by_case) != set(cases):
            raise ValueError(f"window {name}: by_case names every case or none")


def _check_one_case(descriptor: SessionDescriptor) -> None:
    """Refuse a session of one case whose case says something else than the session."""
    case_id, case = next(iter(descriptor.cases.items()))
    if case.config_hash != descriptor.config_hash:
        raise ValueError(f"case {case_id} and its session carry different config hashes")
    best = descriptor.best
    if best is None or case_id not in best.cases:
        return
    if not _same_cost(best.cases[case_id].cost, best.cost):
        raise ValueError(f"case {case_id} and the best trial carry different costs")


def _same_cost(first: float | None, second: float | None) -> bool:
    """Whether two costs are the same number; ``NaN`` is the same as itself."""
    return first == second or (first != first and second != second)


def session_descriptor_path(session_dir: str | Path) -> Path:
    """Return ``<session>/session.json``."""
    return Path(session_dir) / SESSION_DESCRIPTOR_FILENAME


def write_session(session_dir: str | Path, descriptor: SessionDescriptor) -> Path:
    """Write the descriptor durably and return its path."""
    return write_json_durable(session_descriptor_path(session_dir), dump_stored(descriptor))


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


def latest_session_dir(project_root: str | Path, case_id: str) -> Path | None:
    """Return the session directory of *case_id* with the highest version, or None."""
    from hydromodpy.results.catalog.registration import split_stem_version

    best: tuple[int, Path] | None = None
    for directory in list_session_dirs(project_root):
        stem, version = split_stem_version(directory.name)
        number = 1 if version is None else version
        if stem == case_id and (best is None or number > best[0]):
            best = (number, directory)
    return None if best is None else best[1]


def find_session_dir(project_root: str | Path, session_id: str) -> Path | None:
    """Return the directory of the session whose descriptor carries *session_id*."""
    wanted = str(session_id).replace("-", "").lower()
    for directory, descriptor in readable_documents(read_session, list_session_dirs(project_root)):
        if descriptor.session_id.replace("-", "").lower() == wanted:
            return directory
    return None


def _read_phases_and_trials(session_dir: Path) -> bool:
    """Read what a session holds beside its descriptor; a document this code refuses raises."""
    from hydromodpy.results.session.journal import read_trials
    from hydromodpy.results.session.phase import list_phases

    list_phases(session_dir)
    read_trials(session_dir)
    return True


def resolve_session_dir(project_root: str | Path, reference: str | None) -> Path:
    """Return the session directory a reference names.

    ``reference`` is ``<case>[.vN]`` or ``sessions/<case>[.vN]``, the exact
    name of one session. ``None`` selects the session that started last among
    those this code reads, whole: its descriptor, its phases and its journal.
    A session one of them refuses costs one warning. A reference that names no
    session is refused with the sessions the project holds.
    """
    root = Path(project_root).expanduser().resolve()
    sessions = list_session_dirs(root)
    if reference is None:
        started = {
            directory: descriptor.started_at
            for directory, descriptor in readable_documents(read_session, sessions)
        }
        for directory in sorted(started, key=started.__getitem__, reverse=True):
            if readable(_read_phases_and_trials, directory):
                return directory
        raise ConfigMissingError(f"No readable calibration session under {sessions_dir_for(root)}.")
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
    "BestCase",
    "BestTrial",
    "CostInterval",
    "ParameterBound",
    "ParameterWidth",
    "ProtocolDeparture",
    "RestartRange",
    "ScoredSamples",
    "SessionCase",
    "SessionDescriptor",
    "SessionProtocol",
    "SessionStatus",
    "check_case_tables",
    "find_session_dir",
    "list_session_dirs",
    "read_session",
    "resolve_session_dir",
    "scored_samples_text",
    "session_descriptor_path",
    "write_session",
]
