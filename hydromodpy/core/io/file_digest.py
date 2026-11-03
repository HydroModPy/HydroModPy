"""The one SHA-256 digest of a file on disk."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1 << 20
"""Bytes read at a time, so a large store never sits in memory."""


def sha256_of(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["CHUNK_BYTES", "sha256_of"]
