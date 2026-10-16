"""The version rule of every stored document.

Every document HydroModPy writes on disk carries its version: a ``schema``
id such as ``hydromodpy.outcome.v1``, an integer ``*_version`` field, or the
``schema_version`` row of the index. A reader refuses a document that carries
none, or one it does not know, with
:class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`. The message
names the version read, the version this code reads and what to do. Stored
data is never migrated, so what to do is a gesture, never a rewrite:

- the index (``.hmp/index.duckdb``) is rebuilt with ``hmp catalog reindex``;
- a sealed document is read with the HydroModPy version that wrote it
  (:func:`sealed_remedy`);
- a transient document (a pulse, the facts of an attempt, a lease) is
  deleted, and the run starts again (:data:`TRANSIENT_REMEDY`).

The one migration HydroModPy keeps is the grammar of a configuration file,
in :mod:`hydromodpy.config.config_migration`: a configuration is an input,
never stored data.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION

TRANSIENT_REMEDY: Final[str] = "It is transient state: delete it and run again."
"""What to do with a transient document of another version."""


def sealed_remedy(hydromodpy_version: str | None) -> str:
    """Return what to do with a sealed document of another version."""
    written = hydromodpy_version if hydromodpy_version else "unknown"
    return f"Read it with the HydroModPy version that wrote it, hydromodpy_version = {written}."


def check_version(
    found: object,
    expected: object,
    *,
    document: str | Path,
    key: str,
    remedy: str,
) -> None:
    """Refuse *found* unless it is *expected*.

    *document* names the file (or the index) in the message, *key* the field
    that holds the version, *remedy* what to do.
    """
    if found == expected:
        return
    read = f"carries no {key}" if found is None else f"has {key} = {found!r}"
    raise SchemaVersionMismatchError(
        f"{document} {read}; HydroModPy {HYDROMODPY_VERSION} reads {key} = {expected!r}. {remedy}",
        document=str(document),
        found=found,
        expected=expected,
    )


def check_document(
    payload: Any,
    expected: object,
    *,
    document: str | Path,
    remedy: str,
    key: str = "schema",
) -> Mapping[str, Any]:
    """Return *payload* when its *key* is *expected*; refuse it otherwise.

    A payload that is not a JSON object carries no version and is refused
    the same way.
    """
    found = payload.get(key) if isinstance(payload, Mapping) else None
    check_version(found, expected, document=document, key=key, remedy=remedy)
    return payload


__all__ = [
    "TRANSIENT_REMEDY",
    "check_document",
    "check_version",
    "sealed_remedy",
]
