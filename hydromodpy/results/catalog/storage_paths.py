"""Filesystem path resolution for run artefacts.

A run owns one directory, ``runs/<name>``, named after the run itself
(``cheze_demo``, ``cheze_demo.v2`` ...). Everything the run produced lives
inside it: ``fields.zarr``, ``tables.parquet/<view>.parquet``,
``config.toml``, ``figures/``. The layout is therefore readable without the
index, and deleting a run is deleting one directory.

The run name is mutable: renaming a run moves its directory, so the index
and the tree never disagree. :meth:`StoragePathResolver.move` performs that
move and is the only place allowed to do so.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    TABLES_DIRNAME,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog.ports import CatalogBackend

_UNSAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9._-]+")
_COLLAPSE_UNDERSCORE_RE = re.compile(r"_+")
_SAFE_CHAR_RE = re.compile(r"[^a-z0-9_-]+")

MAX_SEGMENT_LEN = 32
MAX_DIRNAME_LEN = 96
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


class RunNameTooLongError(ValueError):
    """A run name maps to a directory name longer than the filesystem budget."""

    def __init__(self, name: str, length: int) -> None:
        super().__init__(
            f"Run name {name!r} maps to a {length}-character directory name; "
            f"the maximum is {MAX_DIRNAME_LEN} characters. Shorten the name."
        )
        self.name = name
        self.length = length


def run_dirname(name: str | None) -> str:
    """Return the directory name of a run from its human name.

    Case is preserved (the directory is meant to be recognised at a glance)
    and the ``.vN`` version suffix survives; only characters a filesystem
    cannot carry are folded to ASCII and replaced by an underscore.

    A name that would need more than :data:`MAX_DIRNAME_LEN` characters is
    refused with :class:`RunNameTooLongError` rather than truncated: two names
    sharing a prefix would otherwise resolve to the same directory and the
    second run would die on a collision it never asked for.
    """
    if not name:
        return UNNAMED
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE_CHAR_RE.sub("_", folded.strip())
    cleaned = _COLLAPSE_UNDERSCORE_RE.sub("_", cleaned).strip("._-")
    if not cleaned:
        return UNNAMED
    if len(cleaned) > MAX_DIRNAME_LEN:
        raise RunNameTooLongError(str(name), len(cleaned))
    return cleaned


class StoragePathResolver:
    """Resolve and cache the on-disk directory of each run.

    Holds the ``runs/`` root and an in-memory ``sim_id → dirname`` cache so
    per-run paths can be computed without a fresh DuckDB lookup on every
    access.
    """

    def __init__(self, backend: CatalogBackend, runs_dir: Path) -> None:
        self._backend = backend
        self._runs_dir = runs_dir
        self._dirname_cache: dict[str, str] = {}

    @property
    def runs_dir(self) -> Path:
        """Root directory holding one sub-directory per run."""
        return self._runs_dir

    def dirname_for(self, sim_id: str | UUID) -> str:
        """Return the directory name of ``sim_id``.

        Reads the run name through the catalog backend port. A trashed run
        has a NULL ``name`` (the bare name is freed on trash) but keeps
        ``original_name``, so its directory stays resolvable and deletable.
        An unknown ``sim_id`` falls back to its short id, which keeps path
        computation total.
        """
        sid = str(sim_id)
        cached = self._dirname_cache.get(sid)
        if cached is not None:
            return cached
        row = self._backend.fetch_one(
            "SELECT COALESCE(name, original_name) FROM simulations WHERE sim_id = ?",
            [sid],
        )
        name = row[0] if row and row[0] else sid[:8]
        dirname = run_dirname(name)
        self._dirname_cache[sid] = dirname
        return dirname

    def cache_dirname(self, sim_id: str | UUID, dirname: str) -> None:
        """Pre-populate the cache for a freshly registered run."""
        self._dirname_cache[str(sim_id)] = dirname

    def forget(self, sim_id: str | UUID) -> None:
        """Drop the cached directory name for ``sim_id`` (used on delete)."""
        self._dirname_cache.pop(str(sim_id), None)

    def move(self, sim_id: str | UUID, new_dirname: str) -> Path:
        """Move the run directory to ``new_dirname`` and return the new path.

        Called by a rename so the tree follows the name. A missing source
        directory is not an error (the run has not written anything yet);
        an already-taken destination is, since two runs must never share a
        directory.
        """
        source = self.run_dir_for(sim_id)
        target = self._runs_dir / new_dirname
        if source != target:
            if target.exists():
                raise FileExistsError(f"Run directory already exists: {target}")
            if source.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
        self.cache_dirname(sim_id, new_dirname)
        return target

    def run_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the run directory (may not yet exist)."""
        return self._runs_dir / self.dirname_for(sim_id)

    def fields_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr directory store of the run."""
        return self.run_dir_for(sim_id) / FIELDS_STORE_NAME

    def tables_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the directory holding the run's Parquet payloads."""
        return self.run_dir_for(sim_id) / TABLES_DIRNAME

    def table_path_for(self, sim_id: str | UUID, view_name: str) -> Path:
        """Return the Parquet payload path for ``view_name``."""
        return self.tables_dir_for(sim_id) / f"{view_name}{PARQUET_FILE_SUFFIX}"

    def config_path_for(self, sim_id: str | UUID) -> Path:
        """Return the frozen configuration path of the run."""
        return self.run_dir_for(sim_id) / RUN_CONFIG_FILENAME

    def figures_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the figures directory of the run."""
        return self.run_dir_for(sim_id) / RUN_FIGURES_DIRNAME
