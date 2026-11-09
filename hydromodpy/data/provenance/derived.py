"""Where a copy derived from a user file lives, and what it is named.

A loader of a user file may write a copy of it: a clip, a Voronoi
tessellation, a format conversion. That copy is no fetched file, so it never
goes into ``data/<variable>/``, where every sidecar is a row of the data cache.
The copy goes under ``data/blobs/<variable>/file/``, a folder the scan of the
cache never enters. Its name carries the source stem and a key of the inputs
that produced it, so two projects that derive different copies from one file
never overwrite each other.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path


def derived_dir(data_dir: Path | None, variable: str) -> Path | None:
    """Return ``data/blobs/<variable>/file/`` for the variable folder ``data_dir``.

    ``data_dir`` is ``data/<variable>/``. The answer is None when there is no
    data folder, and the loader then references the user file as it is.
    """
    if data_dir is None:
        return None
    return Path(data_dir).parent / "blobs" / variable / "file"


def derived_path(
    derived_dir: Path,
    source: Path,
    *,
    kind: str,
    suffix: str,
    inputs: Sequence[str] = (),
) -> Path:
    """Return the path of the copy of ``source`` derived by ``kind``.

    The name is ``<stem>_<kind>_<key><suffix>``. The key hashes the source
    path and ``inputs``, the other values the copy depends on (a bbox, a lake
    id). The same inputs give the same path, different inputs a different one.
    """
    token = "|".join([str(source), *inputs])
    key = hashlib.sha256(token.encode()).hexdigest()[:8]
    return Path(derived_dir) / f"{Path(source).stem}_{kind}_{key}{suffix}"


__all__ = ["derived_dir", "derived_path"]
