"""What a named calibration protocol is.

A protocol is a published calibration method: an ordered set of stages, each
with the parameters it moves, the criterion it is scored on and the model regime
it needs. Naming one in a file replaces the assembly a project would otherwise
retype, and records what the result rests on.

A protocol reads and returns plain mappings, before any model validates them, so
it can write into sections other than ``[calibration]`` and stays independent of
the configuration classes it feeds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable


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

    support: Mapping[str, BackendSupport]
    """What running this protocol on each solver backend is worth, per the
    closed vocabulary above."""

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


__all__ = ["CalibrationProtocol", "Reference"]
