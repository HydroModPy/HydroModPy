"""Atomic JSON documents of a run, a session, a plan or a publication.

Why
---
Every JSON file a run directory carries is read by other processes while it
is being written: a launcher polling ``outcome.json``, an indexer reading
``manifest.json``, a watcher reading ``logs/heartbeat.json``. A reader must
see the previous document or the new one, never a truncated one. So every
document is written to a sibling temporary file and renamed onto its target
in one step.

Two writers, one difference
---------------------------
``write_json_atomic`` renames and stops: enough for a pulse or a ledger,
which the next write refreshes anyway. ``write_json_durable`` also calls
``fsync`` on the file before the rename and on the directory after it, so
the document survives a power cut. The seal (``manifest.json``) and the
issue (``outcome.json``) are durable; nothing else needs to be.

Format
------
Indented UTF-8 JSON, keys in the order the model dumped them, one trailing
newline. A payload is JSON-native already: models dump with
``model_dump(mode="json")`` before they reach this module, so there is no
``default=`` escape hatch and a value that cannot be rendered is a bug.

Versions
--------
Every document carries its version, and the rule is
:mod:`hydromodpy.core.io.document_version`. :func:`read_sealed_json` reads a
sealed document whose version lies in the window of its family, and names
the HydroModPy version that wrote any other, read from the document or from
the seal beside it. :func:`read_transient_json` reads one exact version and
says to delete any other.

Unreadable documents
--------------------
A read that builds a list or takes a decision goes through :func:`readable`.
A document that cannot be read costs one warning naming it and is left out,
so one run of another version never stops a listing. A read of the one
document a gesture names keeps its refusal.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Final, TypeVar

from hydromodpy.core.exceptions import StorageError
from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.io.document_version import (
    TRANSIENT_REMEDY,
    VersionWindow,
    check_document,
    check_version,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.results.storage.contract import (
    RUN_MANIFEST_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
)

logger = get_logger(__name__)

T = TypeVar("T")

UNREADABLE_ERRORS: Final[tuple[type[Exception], ...]] = (StorageError, OSError, ValueError)
"""What a document that cannot be read raises: a version refused, a file gone or
unreachable, a text that is no JSON, a payload its model refuses."""

_warned_unreadable: set[str] = set()
"""The documents this process already warned about: a list is built many times."""

_SEALS: tuple[str, ...] = (RUN_MANIFEST_FILENAME, SESSION_DESCRIPTOR_FILENAME)
"""Documents beside a sealed one that name the version that wrote the directory."""


def render_json(payload: Any) -> str:
    """Render *payload* as the exact text a document carries."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def read_json(path: str | Path) -> Any:
    """Read a document back."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_sealed_json(path: str | Path, window: VersionWindow, *, key: str = "schema") -> Any:
    """Read a sealed document; refuse it unless its *key* lies inside *window*."""
    target = Path(path)
    return check_sealed(read_json(target), window, path=target, key=key)


def check_sealed(
    payload: Any,
    window: VersionWindow,
    *,
    path: str | Path,
    key: str = "schema",
    line: int | None = None,
) -> Any:
    """Return a sealed *payload* read from *path*; refuse it unless its *key* lies in *window*.

    *line* names the line of a JSON Lines document in the message.
    """
    found = payload.get(key) if isinstance(payload, Mapping) else None
    if not window.holds(found):
        target = Path(path)
        document = str(target) if line is None else f"{target}:{line}"
        writer = writer_version(payload, target)
        check_version(found, window, document=document, key=key, writer=writer)
    return payload


def read_transient_json(path: str | Path, expected: object, *, key: str = "schema") -> Any:
    """Read a transient document; refuse it unless its *key* is *expected*."""
    target = Path(path)
    return check_document(
        read_json(target), expected, document=target, key=key, remedy=TRANSIENT_REMEDY
    )


def warn_unreadable(path: str | Path, reason: object) -> None:
    """Warn that *path* is left out and why, once per process."""
    named = str(path)
    if named not in _warned_unreadable:
        _warned_unreadable.add(named)
        logger.warning("%s is left out: %s", named, reason)


def readable(read: Callable[..., T], path: str | Path, *args: Any, **kwargs: Any) -> T | None:
    """Return ``read(path, ...)``, or ``None`` when the document cannot be read.

    An unreadable document costs one warning naming it. A missing one says
    nothing: there is no document to leave out.
    """
    try:
        return read(path, *args, **kwargs)
    except FileNotFoundError:
        return None
    except UNREADABLE_ERRORS as exc:
        warn_unreadable(path, exc)
        return None


def readable_documents(
    read: Callable[[Path], T], paths: Iterable[Path]
) -> Iterator[tuple[Path, T]]:
    """Yield each path with what *read* returns, leaving out what cannot be read."""
    for path in paths:
        document = readable(read, path)
        if document is not None:
            yield path, document


def writer_version(payload: Any, path: str | Path) -> str | None:
    """Return the HydroModPy version that wrote a document, or ``None``.

    Read from the document itself, else from the seal of its run or session
    (``manifest.json`` or ``session.json``) up to three folders above it.
    """
    own = _hydromodpy_version_in(payload)
    if own is not None:
        return own
    target = Path(path)
    for folder in list(target.parents)[:3]:
        for name in _SEALS:
            seal = folder / name
            if seal == target or not seal.is_file():
                continue
            try:
                found = _hydromodpy_version_in(read_json(seal))
            except (OSError, ValueError):
                # The version is a hint of the refusal; an unreadable seal leaves it unknown.
                continue
            if found is not None:
                return found
    return None


def _hydromodpy_version_in(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    identity = payload.get("identity")
    tool = payload.get("tool")
    entries = payload.get("entries")
    candidates = (
        payload.get("hydromodpy_version"),
        identity.get("hydromodpy_version") if isinstance(identity, Mapping) else None,
        tool.get("version") if isinstance(tool, Mapping) else None,
        entries[0].get("hydromodpy_version")
        if isinstance(entries, list) and entries and isinstance(entries[0], Mapping)
        else None,
    )
    return next((str(value) for value in candidates if value), None)


def _stage(target: Path, payload: Any) -> Path:
    """Write *payload* to a temporary sibling of *target* and return it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    staged.write_text(render_json(payload), encoding="utf-8")
    return staged


def write_json_atomic(target: str | Path, payload: Any) -> Path:
    """Write *payload* to *target* through a temporary file and one rename."""
    path = Path(target)
    staged = _stage(path, payload)
    try:
        rename_over_open_file(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return path


def write_json_durable(target: str | Path, payload: Any) -> Path:
    """Write *payload* like :func:`write_json_atomic`, then make it survive a power cut.

    The staged bytes are flushed to the disk before the rename, and the
    directory entry after it, so neither the document nor its name can be
    lost once this returns.
    """
    path = Path(target)
    staged = _stage(path, payload)
    try:
        _fsync_file(staged)
        rename_over_open_file(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)
    return path


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entry; a no-op on Windows, which cannot open a directory."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "UNREADABLE_ERRORS",
    "check_sealed",
    "read_json",
    "read_sealed_json",
    "read_transient_json",
    "readable",
    "readable_documents",
    "render_json",
    "warn_unreadable",
    "write_json_atomic",
    "write_json_durable",
    "writer_version",
]
