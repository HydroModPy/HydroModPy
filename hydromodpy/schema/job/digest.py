"""The two digests a job computes, and nothing else computes them twice.

A file is hashed from its bytes, in blocks, because an input raster is
routinely larger than memory. A value is hashed from its canonical JSON, so
two callers that spell the same object differently still get one digest, and
so a key added to it always changes it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from hydromodpy.core.io.canonical_json import dumps as canonical_dumps

_READ_BLOCK = 1024 * 1024


def sha256_file(path: str | Path) -> tuple[str, int]:
    """Return the digest and the size of the bytes at *path*."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while block := handle.read(_READ_BLOCK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def sha256_value(value: Any) -> str:
    """Return the digest of the canonical JSON of *value*."""
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


__all__ = ["sha256_file", "sha256_value"]
