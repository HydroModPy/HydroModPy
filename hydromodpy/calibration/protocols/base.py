"""What a named calibration protocol is.

A protocol is a published calibration method: an ordered set of stages, each
with the parameters it moves, the criterion it is scored on and the model regime
it needs. Naming one in a file replaces the assembly a project would otherwise
retype, and records what the result rests on.

A protocol reads and returns plain mappings, before any model validates them, so
it can write into sections other than ``[calibration]`` and stays independent of
the configuration classes it feeds.

What a protocol asks of a solver backend it says once: the observables its
stages read. Nothing here spells a backend name. ``tested`` verdicts sit in a
data file beside the protocols, and a refusal is the backend's own answer.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from hydromodpy.core.exceptions import SolverInputError


@dataclass(frozen=True)
class Reference:
    """One bibliographic entry a protocol rests on."""

    key: str
    authors: str
    year: int
    title: str
    venue: str
    doi: str

    def cite(self) -> str:
        """Return the entry as one citation line."""
        return f"{self.authors} ({self.year}). {self.title}. {self.venue}. doi:{self.doi}"


BackendSupport = Literal["tested", "expected_untested", "unsupported"]
"""A closed vocabulary, because "supported" alone hides the difference that matters.

``tested`` means a case in this repository runs the protocol on that backend.
``expected_untested`` means nothing structural forbids it and nobody has run it,
which is an honest thing to publish and a dishonest thing to leave unsaid.
``unsupported`` means the backend cannot serve what the protocol needs.
"""


@dataclass(frozen=True)
class ProtocolSupport:
    """One support verdict, and the backend reason naming it when refused."""

    verdict: BackendSupport

    reason: str | None = None
    """The reason the backend declares for an ``unsupported`` verdict.

    Read off ``declared_observables``, so a sentence about a refusal comes from
    the backend and not from a table beside the protocol.
    """


def backends_tested_in_this_repository(protocol_name: str) -> frozenset[str]:
    """Return the backends a case in this repository runs, from the tested table."""
    with (Path(__file__).with_name(TESTED_TABLE)).open("rb") as handle:
        rows = tomllib.load(handle)
    verdicts = rows.get(protocol_name, {})
    return frozenset(str(name) for name, verdict in verdicts.items() if str(verdict) == "tested")


def protocol_support(
    protocol: CalibrationProtocol,
    backend: str | None,
    active: frozenset[str] | None = None,
) -> ProtocolSupport:
    """Return what one backend serves a protocol, before anything runs.

    ``tested`` reads the table beside the protocols, which names what a case in
    this repository runs. ``unsupported`` is the backend's own answer, read off
    ``declared_observables``: the protocol lists the observables its stages
    read, and a backend that declares one of them out of reach cannot serve any
    stage. ``under_condition`` never refuses, because it is one declaration
    away. ``expected_untested`` covers the rest, a name the registry cannot
    build included, because nothing structural forbids it and nobody has run it.
    """
    if backend is not None and str(backend) in backends_tested_in_this_repository(protocol.name):
        return ProtocolSupport(verdict="tested")
    needed = tuple(getattr(protocol, "declared_observables", ()) or ())
    if backend is None or not needed:
        return ProtocolSupport(verdict="expected_untested")
    try:
        from hydromodpy.solver.base.registry import solvers

        adapter = solvers.create("flow", str(backend))
    except (SolverInputError, ValueError):
        return ProtocolSupport(verdict="expected_untested")
    declared = getattr(adapter, "declared_observables", None)
    if declared is None:
        return ProtocolSupport(verdict="expected_untested")
    for item in declared(frozenset(active or ())):
        if str(getattr(item, "name", "")) in needed and getattr(item, "state", "") == "unavailable":
            reason = str(getattr(item, "reason", "")) or None
            return ProtocolSupport(verdict="unsupported", reason=reason)
    return ProtocolSupport(verdict="expected_untested")


def support_by_backend(
    protocol: CalibrationProtocol, backends: list[str] | None = None
) -> dict[str, str]:
    """Return one support verdict per named backend, shipped names included.

    ``backends`` is every flow backend this build ships plus the one a session
    ran; a verdict read here never depends on the plugins installed beside this
    build, and it reads the same thing a sentence in the method text reads.
    """
    from hydromodpy.solver.base.registry import solvers

    names = set(backends or ())
    names |= set(solvers.names("flow", shipped_only=True))
    names |= backends_tested_in_this_repository(protocol.name)
    return {name: protocol_support(protocol, name).verdict for name in sorted(names)}


TESTED_TABLE = "tested_backends.toml"
"""The data file beside the protocols: one table per protocol name.

It carries only ``tested`` verdicts, naming what a case in this repository runs
on which backend. A backend refusing stays out of it, because a refusal is the
backend's own answer, read off ``declared_observables`` the same way the port of
the solver answers, and it cannot outlive what the backend declares.
"""


@dataclass(frozen=True)
class Deviation:
    """One place this implementation departs from the published method.

    A protocol that silently improves on its paper is no longer that paper's
    method, and a result compared against the literature has to be able to say
    where the two part company.
    """

    key: str
    """The configuration key that carries the departure, when one exists.

    A key of the network output is a dotted path under it, ``map.drawn_by``. A key
    the output does not hold, such as ``dem_correc_type``, is a bare name.

    Some departures have no adjustable knob at all (a hardcoded default such as
    sealing the outlet into a target): the key then names the concept for a
    reader, and no file value is ever compared against it.
    """

    paper: str
    """What the publication does."""

    here: str
    """What this implementation does by default."""

    why: str
    """Why the departure is defended, in one sentence."""

    paper_value: Any = None
    """The value that reproduces the publication, when ``key`` names a real option.

    Compared against a file's own value to decide whether a run actually left
    the publication: a file that pins ``key`` to ``paper_value`` matches it and
    must not be reported as a departure, which is what the Methods paragraph
    (:mod:`hydromodpy.calibration.protocols.boilerplate`) checks this against.
    ``None`` is a valid publication value: an option the publication has no use
    for, which departs once it holds a value.
    """

    always: bool = False
    """True when no value of an option brings the run back to the publication.

    The departure holds in every run, so it is declared and printed as such, and
    ``paper_value`` has nothing to be compared with.
    """

    holds: Callable[[Any, Any], bool] | None = None
    """For a departure that depends on what the file writes with no value of its own.

    Called with the validated ``[calibration]`` section and ``[metrics] window``
    (a mapping, its model or ``None``). True when this run leaves the publication
    on this point, false when the file's declarations bring it back. Not combined
    with ``always``.
    """


@runtime_checkable
class CalibrationProtocol(Protocol):
    """A named method that writes a calibration assembly into a document.

    Implementations are registered in
    :mod:`hydromodpy.calibration.protocols.registry`. Nothing imports them
    directly: a file names one, and the registry resolves it.
    """

    name: str
    """Identifier written as ``[calibration].protocol``."""

    version: str
    """The recipe's own version, pinned by a file that has to be replayable.

    A number that informed a decision must be reproducible with the recipe of its
    era, not with whatever the recipe became. A file may pin this or an older line
    of ``defaults_by_version``; another version is refused rather than approximated
    by the current one."""

    title: str
    """One line naming the method as a reader would say it."""

    summary: str
    """What the method does and what it assumes, in a short paragraph."""

    stages: tuple[str, ...]
    """One line per stage, in the order they run."""

    references: tuple[Reference, ...]
    """The publications the method is defined in."""

    declared_observables: tuple[str, ...]
    """The observables the stages of this method read, by their name.

    ``release_flux``, ``discharge`` and the like, the same names a backend
    answers in ``declared_observables``. The support verdict is read off the
    backend's own answer and off the tested table of this package, so no
    backend name is spelled here.
    """

    deviations: tuple[Deviation, ...]
    """Where this implementation departs from the publication, and why."""

    defaults_by_version: Mapping[str, Mapping[str, Any]]
    """What each version carried writes for the keys a file leaves empty."""

    adjustable: frozenset[str]
    """Which options a file may change and still be running this protocol.

    Anything outside is a variant, not a setting, and the record says so rather
    than letting a file claim a method it has left."""

    def expand(self, options: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
        """Return a new document carrying the assembly this protocol defines.

        ``options`` is the ``[calibration.protocol]`` table minus its ``name``.
        ``document`` is the whole configuration payload, so a protocol can read
        the simulation window its stages have to fit and write the overrides
        they need. The input is never mutated.
        """
        ...


__all__ = [
    "BackendSupport",
    "CalibrationProtocol",
    "ProtocolSupport",
    "Reference",
    "TESTED_TABLE",
    "protocol_support",
    "support_by_backend",
    "backends_tested_in_this_repository",
]
