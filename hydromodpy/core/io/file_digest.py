"""The one SHA-256 digest of a file on disk."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1 << 20
"""Bytes read at a time, so a large store never sits in memory."""


def sha256_of(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    return sha256_and_size(path)[0]


def sha256_and_size(path: str | Path) -> tuple[str, int]:
    """Return the hex SHA-256 and the size in bytes of a file, read in chunks."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


__all__ = ["CHUNK_BYTES", "sha256_and_size", "sha256_of"]
