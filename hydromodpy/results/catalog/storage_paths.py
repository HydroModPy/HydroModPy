"""Filesystem path resolution for run artifacts.

A run owns one directory, ``runs/<name>`` or a kept trial
``sessions/<name>/trials/<nnnn>``, named after the run itself (``my_run``,
``my_run.v2`` ...). Everything the run produced lives inside it:
``fields.zarr``, ``tables.parquet/<view>.parquet``, ``config.toml``,
``figures/``. The layout is therefore readable without the index, and
deleting a run is moving one directory to the trash.

The index holds the relative directory of each run (``rel_dir``), and
:class:`StoragePathResolver` reads it back. Moving a directory is never done
here: :func:`hydromodpy.results.catalog.registration.rename_case` renames,
:mod:`hydromodpy.results.trash` trashes and restores.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.result_dirs import parse_rel_dir
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


class RunNameTooLongError(ConfigError, ValueError):
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

    Case is preserved (the directory is meant to be recognized at a glance)
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
    """Resolve and cache the on-disk directory of each indexed run.

    Holds the project root and an in-memory ``sim_id -> rel_dir`` cache, so
    per-run paths are computed without a fresh DuckDB lookup on every access.
    """

    def __init__(self, backend: CatalogBackend, project_root: Path) -> None:
        self._backend = backend
        self._project_root = Path(project_root)
        self._rel_dir_cache: dict[str, str] = {}

    def rel_dir_for(self, sim_id: str | UUID) -> str:
        """Return the relative directory the index holds for ``sim_id``.

        Raises ``KeyError`` for a ``sim_id`` the index does not know: a path
        made up for an unknown run would point at another run, or at nothing.
        """
        sid = str(sim_id)
        cached = self._rel_dir_cache.get(sid)
        if cached is not None:
            return cached
        row = self._backend.fetch_one(
            "SELECT rel_dir FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?", [sid]
        )
        if row is None or not row[0]:
            raise KeyError(f"No run with sim_id={sid[:8]} in the index")
        rel_dir = parse_rel_dir(str(row[0])).as_posix()
        self._rel_dir_cache[sid] = rel_dir
        return rel_dir

    def forget(self, sim_id: str | UUID) -> None:
        """Drop the cached directory of ``sim_id`` (its row changed or went away)."""
        self._rel_dir_cache.pop(str(sim_id), None)

    def run_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the run directory (may not yet exist)."""
        return self._project_root / self.rel_dir_for(sim_id)

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
