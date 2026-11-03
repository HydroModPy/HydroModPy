"""Record a derived file of a run in the ledger of its directory.

A figure goes to ``runs/<run>/figures/`` and an export to
``runs/<run>/exports/``. Each directory keeps one ``index.json``
(:mod:`hydromodpy.results.ledger`) with one entry per file: who wrote it, with
which options, under which version, its digest and the identity block it
carries. ``hmp export --regen`` replays these entries.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.identity import Identity
from hydromodpy.results.ledger import Ledger, LedgerEntry, sha256_of


def record_derived_file(
    directory: str | Path,
    path: str | Path,
    *,
    producer: str,
    options: Mapping[str, Any],
    identity: Identity,
) -> LedgerEntry:
    """Add the entry of *path* to the ledger of *directory* and return it.

    *path* lies under *directory*; the entry names it relative to it. An entry
    for the same file is replaced: one file, one entry.
    """
    root = Path(directory)
    target = Path(path)
    entry = LedgerEntry(
        file=target.resolve().relative_to(root.resolve()).as_posix(),
        producer=producer,
        options=dict(options),
        hydromodpy_version=HYDROMODPY_VERSION,
        at=datetime.now(UTC),
        sha256=sha256_of(target),
        identity=identity,
    )
    ledger = Ledger.read(root)
    ledger.append(entry)
    ledger.write(root)
    return entry


__all__ = ["record_derived_file"]
