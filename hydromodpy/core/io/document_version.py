"""The version rule of every stored document.

Every document HydroModPy writes on disk carries its version: a ``schema`` id
such as ``hydromodpy.outcome.v1``, an integer ``*_version`` field, a string
such as ``"3"`` or ``"v2"``, or the ``schema_version`` row of the index. A reader
refuses a document that carries none, or one it does not read, with
:class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`. The message names
the version read, the version that wrote it when known, what this code reads and
what to do.

A family of sealed documents declares a :class:`VersionWindow` next to its
current constant, the oldest version it reads and the current one, so every
later 2.x reads every document of the 2.0.0 release. The two bounds are equal at 2.0.0. The
rule of a change, for the whole 2.x line:

- adding an optional field, column or array does not change the version, and
  an older reader ignores what it does not know;
- a change a reader cannot ignore raises ``current`` and keeps ``oldest``, and
  it brings the reader of the old version with it;
- ``oldest`` never moves up inside a major version.

A document outside the window is refused by what it is:

- newer than the window: upgrade HydroModPy to read it;
- older than the window, or with no version: a pre-release wrote it, so it
  must be run again.

Two kinds of document keep an exact version (:func:`check_exact`), because
what they hold can be made again. The index (``.hmp/index.duckdb``) is rebuilt
with ``hmp catalog reindex``. A transient document (a pulse, the facts of an
attempt, a lease) is deleted and the run starts again (:data:`TRANSIENT_REMEDY`).

Nothing upgrades a stored document to another version in place. Sealed files
stay as they were written. The living ones (``annotations.json``, ``outcome.json``,
``session.json``, ``phases/<p>/session.json``, the ledgers) are written again by
the commands that own them, at their version, and such a rewrite keeps what it
does not understand (:func:`~hydromodpy.core.config_kit.stored.dump_stored`). The
one migration of a file HydroModPy keeps is the grammar of a configuration, which
:mod:`hydromodpy.config.config_migration` reads from the rows of ``schema/changes.toml``,
because a configuration is an input.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION

TRANSIENT_REMEDY: Final[str] = "It is transient state: delete it and run again."
"""What to do with a transient document of another version."""

NEWER_REMEDY: Final[str] = "It is newer than this code: upgrade HydroModPy to read it."
"""What to do with a sealed document newer than the window."""

OLDER_REMEDY: Final[str] = "It was written by a pre-release of HydroModPy and must be run again."
"""What to do with a sealed document older than the window, or with no version."""

FOREIGN_REMEDY: Final[str] = "It is another kind of document."
"""What to say of a document whose ``schema`` id names another family."""

_VERSION_TEXT: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?P<family>[A-Za-z_][\w.\-]*)[./])?v?(?P<number>\d+(?:\.\d+){0,2})$"
)

Standing = Literal["inside", "newer", "older", "foreign"]
"""Where a found version stands against a window."""


def parse_version(value: object) -> tuple[str | None, tuple[int, int, int]] | None:
    """Return the family and the number of a version, ``None`` when it is not one.

    Every form a stored document uses reads here: ``2``, ``"3"``, ``"v2"``,
    ``"hydromodpy.outcome.v1"`` and ``"hmp-outcome/v1"``. A number may have up to
    three parts, such as ``"2.0.0"``, and a missing part counts as 0.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return (None, (value, 0, 0)) if value >= 0 else None
    if not isinstance(value, str):
        return None
    match = _VERSION_TEXT.match(value)
    if match is None:
        return None
    parts = [int(part) for part in match["number"].split(".")]
    major, minor, patch = (*parts, 0, 0)[:3]
    return match["family"], (major, minor, patch)


@dataclass(frozen=True, slots=True)
class VersionWindow:
    """The versions of one family of sealed documents this code reads, both bounds included."""

    oldest: object
    """The oldest version this code reads, as a document writes it."""
    current: object
    """The version this code writes, as a document writes it."""

    def __post_init__(self) -> None:
        low, high = parse_version(self.oldest), parse_version(self.current)
        if low is None or high is None or low[0] != high[0] or low[1] > high[1]:
            raise ValueError(f"{self.oldest!r} to {self.current!r} is not a window of versions")

    def standing(self, found: object) -> Standing:
        """Return where *found* stands; a value that is no version reads as older."""
        parsed = parse_version(found)
        if parsed is None:
            return "older"
        low, high = parse_version(self.oldest), parse_version(self.current)
        assert low is not None and high is not None
        if parsed[0] != high[0]:
            return "foreign"
        if parsed[1] > high[1]:
            return "newer"
        return "older" if parsed[1] < low[1] else "inside"

    def holds(self, found: object) -> bool:
        """Return whether a document of version *found* is read."""
        return self.standing(found) == "inside"

    def reads(self, key: str) -> str:
        """Return what this code reads, in words."""
        if self.oldest == self.current:
            return f"{key} = {self.current!r}"
        return f"{key} = {self.oldest!r} to {self.current!r}"


_REMEDIES: Final[dict[Standing, str]] = {
    "newer": NEWER_REMEDY,
    "older": OLDER_REMEDY,
    "foreign": FOREIGN_REMEDY,
}


def check_version(
    found: object,
    window: VersionWindow,
    *,
    document: str | Path,
    key: str,
    writer: object = None,
    remedy: str | None = None,
) -> None:
    """Refuse *found* unless it lies inside *window*.

    *document* names the file in the message, *key* the field that holds the
    version, *writer* the HydroModPy version that wrote it when known.
    *remedy* replaces what a sealed document is told to do, for a document
    that can be written again.
    """
    standing = window.standing(found)
    if standing == "inside":
        return
    _refuse(
        found,
        window.current,
        window.reads(key),
        document,
        key,
        writer,
        remedy or _REMEDIES[standing],
    )


def check_exact(
    found: object,
    expected: object,
    *,
    document: str | Path,
    key: str,
    remedy: str,
) -> None:
    """Refuse *found* unless it is *expected*, for a document that can be made again."""
    if found != expected:
        _refuse(found, expected, f"{key} = {expected!r}", document, key, None, remedy)


def check_document(
    payload: Any,
    expected: object,
    *,
    document: str | Path,
    remedy: str,
    key: str = "schema",
) -> Mapping[str, Any]:
    """Return *payload* when its *key* is exactly *expected*; refuse it otherwise.

    A payload that is not a JSON object carries no version and is refused
    the same way.
    """
    found = payload.get(key) if isinstance(payload, Mapping) else None
    check_exact(found, expected, document=document, key=key, remedy=remedy)
    return payload


def _refuse(
    found: object,
    expected: object,
    reads: str,
    document: str | Path,
    key: str,
    writer: object,
    remedy: str,
) -> None:
    read = f"carries no {key}" if found is None else f"has {key} = {found!r}"
    written = f", written by HydroModPy {writer}" if writer else ""
    raise SchemaVersionMismatchError(
        f"{document} {read}{written}; HydroModPy {HYDROMODPY_VERSION} reads {reads}. {remedy}",
        document=str(document),
        found=found,
        expected=expected,
    )


__all__ = [
    "FOREIGN_REMEDY",
    "NEWER_REMEDY",
    "OLDER_REMEDY",
    "TRANSIENT_REMEDY",
    "VersionWindow",
    "check_document",
    "check_exact",
    "check_version",
    "parse_version",
]
