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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


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


@runtime_checkable
class CalibrationProtocol(Protocol):
    """A named method that writes a calibration assembly into a document.

    Implementations are registered in
    :mod:`hydromodpy.calibration.protocols.registry`. Nothing imports them
    directly: a file names one, and the registry resolves it.
    """

    name: str
    """Identifier written as ``[calibration].protocol``."""

    title: str
    """One line naming the method as a reader would say it."""

    summary: str
    """What the method does and what it assumes, in a short paragraph."""

    stages: tuple[str, ...]
    """One line per stage, in the order they run."""

    references: tuple[Reference, ...]
    """The publications the method is defined in."""

    def expand(self, options: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
        """Return a new document carrying the assembly this protocol defines.

        ``options`` is the ``[calibration.protocol]`` table minus its ``name``.
        ``document`` is the whole configuration payload, so a protocol can read
        the simulation window its stages have to fit and write the overrides
        they need. The input is never mutated.
        """
        ...


__all__ = ["CalibrationProtocol", "Reference"]
