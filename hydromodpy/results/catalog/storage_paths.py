"""Filesystem path resolution for catalog artefacts.

A simulation's on-disk state lives at ``simulations/<basename>.zarr`` and
``simulations/<basename>.parquet`` where ``<basename>`` is built from the
simulation's ``(project, name, sim_id)`` so a plain ``ls`` is human readable.
Older workspaces written before this scheme used the bare ``sim_id`` as the
basename; the resolver falls back to that form when ``storage_basename`` is
``NULL`` in the ``simulations`` row.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import duckdb

_SAFE_CHAR_RE = re.compile(r"[^a-z0-9_-]+")
_COLLAPSE_UNDERSCORE_RE = re.compile(r"_+")

MAX_SEGMENT_LEN = 32
SHORT_ID_LEN = 8
SEPARATOR = "__"
UNNAMED = "unnamed"


def sanitize_segment(value: str | None, *, max_len: int = MAX_SEGMENT_LEN) -> str:
    """Return a filesystem-safe lowercase slug from an arbitrary string.

    Accented characters are folded to ASCII (``"écoulement"`` → ``"ecoulement"``)
    and every remaining non-alphanumeric/underscore/hyphen character is
    replaced by an underscore. Runs of underscores collapse to one and the
    result is trimmed on both ends. An empty or whitespace-only input maps
    to ``"unnamed"``.
    """
    if not value:
        return UNNAMED
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    slug = _SAFE_CHAR_RE.sub("_", folded.strip().lower())
    slug = _COLLAPSE_UNDERSCORE_RE.sub("_", slug).strip("_-")
    if not slug:
        return UNNAMED
    return slug[:max_len].rstrip("_-") or UNNAMED


def short_uuid(sim_id: str | UUID) -> str:
    """Return the first :data:`SHORT_ID_LEN` hex characters of ``sim_id``."""
    return str(sim_id).replace("-", "")[:SHORT_ID_LEN]


def build_storage_basename(
    project: str | None,
    name: str | None,
    sim_id: str | UUID,
) -> str:
    """Build the on-disk basename for a simulation's Zarr / Parquet folder.

    The format is ``{project}__{name}__{shortuuid}``; missing ``project`` or
    ``name`` fall back to ``"unnamed"`` so the short UUID still guarantees
    uniqueness within the workspace.
    """
    return SEPARATOR.join(
        (
            sanitize_segment(project),
            sanitize_segment(name),
            short_uuid(sim_id),
        )
    )


class StoragePathResolver:
    """Resolve and cache on-disk paths for a simulation's artefacts.

    Holds the ``simulations/`` root and an in-memory ``sim_id → basename``
    cache so per-simulation Parquet and Zarr paths can be computed without
    a fresh DuckDB lookup on every access.
    """

    def __init__(self, db: duckdb.DuckDBPyConnection, simulations_dir: Path) -> None:
        self._db = db
        self._simulations_dir = simulations_dir
        self._basename_cache: dict[str, str] = {}

    def basename_for(self, sim_id: str | UUID) -> str:
        """Return the on-disk basename for ``sim_id``.

        Reads ``simulations.storage_basename`` and falls back to the raw
        ``sim_id`` string when the column is ``NULL`` - the case for rows
        written before human-readable storage names were introduced.
        """
        sid = str(sim_id)
        cached = self._basename_cache.get(sid)
        if cached is not None:
            return cached
        row = self._db.execute(
            "SELECT storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        basename = (row[0] if row else None) or sid
        self._basename_cache[sid] = basename
        return basename

    def cache_basename(self, sim_id: str | UUID, basename: str) -> None:
        """Pre-populate the basename cache for a freshly registered simulation."""
        self._basename_cache[str(sim_id)] = basename

    def forget(self, sim_id: str | UUID) -> None:
        """Drop the cached basename for ``sim_id`` (used on delete)."""
        self._basename_cache.pop(str(sim_id), None)

    def parquet_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the per-simulation Parquet directory (may not yet exist)."""
        return self._simulations_dir / f"{self.basename_for(sim_id)}.parquet"

    def parquet_path_for(self, sim_id: str | UUID, view_name: str) -> Path:
        """Return the Parquet file path for ``view_name`` under ``sim_id``."""
        return self.parquet_dir_for(sim_id) / f"{view_name}.parquet"

    def zarr_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr artefact path on disk (``.zarr.zip`` if packed)."""
        basename = self.basename_for(sim_id)
        zipped = self._simulations_dir / f"{basename}.zarr.zip"
        if zipped.exists():
            return zipped
        return self._simulations_dir / f"{basename}.zarr"
