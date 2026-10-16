"""Digests and sizes of the files a run reads or writes.

One sha256 for a file, one for a directory tree, one size for either. The
digest of a directory covers the relative path and the content of every
file, in sorted order, so two trees with the same files hash the same
whatever the filesystem order.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_streaming(path: Path | str, chunk_size: int = _CHUNK_SIZE) -> str:
    """Return the sha256 of a file, read in fixed-size chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(root: Path | str) -> str:
    """Return a deterministic sha256 over a directory tree."""
    base = Path(root)
    digest = hashlib.sha256()
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_streaming(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def path_size_bytes(path: Path | str) -> int:
    """Return the size of a file, or the summed size of the files of a directory."""
    target = Path(path)
    if target.is_file():
        return target.stat().st_size
    return sum(item.stat().st_size for item in target.rglob("*") if item.is_file())


__all__ = ["path_size_bytes", "sha256_directory", "sha256_streaming"]
