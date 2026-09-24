"""Read ``hydromodpy.lock`` and hold the process-wide frozen mode.

A lockfile freezes the build environment plus every input artefact that fed
a HydroModPy run. It records:

- ``[hydromodpy]``: package + git commit + python + schema versions.
- ``[binaries]``: solver names + binary SHA-256 + ``--version`` text.
- ``[schema]``: catalog / zarr / parquet schema versions (and config sha256).
- ``[inputs]``: every catalog entry keyed by workspace-relative path with
  ``sha256``, ``bytes`` and ``fetched_at``.
- ``[[artefact]]`` rows: legacy per-artefact detail (``variable``, ``source``,
  ``station_id``) used by frozen-mode replay.

This module reads the file and needs no database. Writing, verifying and
archiving it read the cache index, so they live in
:mod:`hydromodpy.data.registry.freeze`.

The file has one address, ``<project root>/hydromodpy.lock``, built by
:func:`project_lockfile_path` and by nothing else. A command that is not handed
a project root asks :func:`resolve_lockfile_root` for one; a workspace root is
never an answer, because a workspace holds many projects and one shared cache.
Frozen mode carries the project root it was enabled on so a reader never has to
guess it from a database location. :mod:`hydromodpy.project.lockfile` documents
why the project root, and not the workspace, owns the file.

Frozen mode is two module variables: one project is frozen per process. The
runner sets it before a run and clears it after.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.core.exceptions import ConfigError

LOCKFILE_NAME = "hydromodpy.lock"
LOCKFILE_VERSION = "2.0.0"

# Process-wide frozen-mode state. Consulted by data loaders to refuse fresh
# downloads when a lockfile is authoritative, and to know which project's
# lockfile that is.
_FROZEN_MODE: bool = False
_FROZEN_PROJECT_ROOT: Path | None = None


def project_lockfile_path(project_root: Path | str) -> Path:
    """Return ``<project_root>/hydromodpy.lock``, the one address of the lockfile."""
    return Path(project_root).expanduser() / LOCKFILE_NAME


def resolve_lockfile_root(project: Path | str | None = None) -> Path:
    """Return the project root whose lockfile a command addresses.

    An explicit ``project`` is the root. Otherwise the walk up from the current
    directory is the one :func:`hydromodpy.core.state.paths.resolve_project_root`
    owns, and only the miss differs: that helper answers with the starting
    directory so a flat project still resolves, while a lockfile command
    outside any project must not write ``hydromodpy.lock`` into whatever
    directory the shell happened to sit in.

    Every miss raises ``FileNotFoundError``, including the unanchored
    ``configs/`` directory that helper reports as a ``ConfigError``: one
    missing root, one exception type to catch.
    """
    from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, resolve_project_root

    if project is not None:
        return Path(project).expanduser().resolve()
    start = Path.cwd().resolve()
    try:
        root = resolve_project_root(start)
    except ConfigError as exc:
        raise FileNotFoundError(str(exc)) from exc
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise FileNotFoundError(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}: {LOCKFILE_NAME} lives at a "
            "project root, so run from inside a project or name one explicitly."
        )
    return root


def set_frozen_mode(enabled: bool, *, project_root: Path | str | None = None) -> None:
    """Toggle process-wide frozen mode and bind the project it reads.

    ``project_root`` is the directory holding ``hydromodpy.lock`` and is
    required to enable: frozen mode without a project has no lockfile to read.
    Disabling clears the binding.
    """
    global _FROZEN_MODE, _FROZEN_PROJECT_ROOT
    if not enabled:
        _FROZEN_MODE = False
        _FROZEN_PROJECT_ROOT = None
        return
    if project_root is None:
        raise ValueError(
            "Enabling frozen mode requires project_root: hydromodpy.lock is read from "
            "the project root, never guessed."
        )
    _FROZEN_MODE = True
    _FROZEN_PROJECT_ROOT = Path(project_root).expanduser().resolve()


def is_frozen_mode() -> bool:
    """Return whether frozen mode is currently active."""
    return _FROZEN_MODE


def frozen_project_root() -> Path | None:
    """Return the project root frozen mode reads the lockfile from, if bound."""
    return _FROZEN_PROJECT_ROOT


@dataclass(frozen=True)
class LockedArtifact:
    """One locked artefact recorded in the lockfile."""

    variable: str
    source: str
    station_id: str | None
    file_path: str
    sha256: str
    file_mtime: float | None
    size_bytes: int | None
    fetched_at: str


@dataclass(frozen=True)
class LockMismatch:
    """Discrepancy between lockfile and on-disk catalog state."""

    kind: str  # "missing", "sha256"
    variable: str
    source: str
    station_id: str | None
    expected: Any
    observed: Any
    path: str | None = None


# ---------------------------------------------------------------------- helpers


def sha256_of(path: Path, *, chunk: int = 64 * 1024) -> str:
    """Compute the SHA-256 digest of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for buf in iter(lambda: fh.read(chunk), b""):
            hasher.update(buf)
    return hasher.hexdigest()


def read_lockfile_schema_sha256(path: Path | str) -> str | None:
    """Return the ``schema.config_sha256`` recorded in the lockfile, when present.

    Falls back to ``schema.sha256`` for lockfiles written before P9.
    """
    doc = tomlkit.parse(Path(path).read_text())
    schema = doc.get("schema")
    if not isinstance(schema, dict):
        return None
    value = schema.get("config_sha256") or schema.get("sha256")
    return str(value) if value is not None else None


def read_lockfile_inputs(path: Path | str) -> dict[str, dict[str, Any]]:
    """Return the ``[inputs]`` table from the lockfile (rel_path -> payload)."""
    doc = tomlkit.parse(Path(path).read_text())
    raw = doc.get("inputs")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        out[str(key)] = {
            "sha256": str(value.get("sha256", "")),
            "bytes": int(value.get("bytes", 0) or 0),
            "fetched_at": str(value.get("fetched_at", "")),
        }
    return out


def read_lockfile_binaries(path: Path | str) -> dict[str, str | None]:
    """Return ``[binaries]`` payload (``<solver>_sha256`` etc.) as a flat dict."""
    doc = tomlkit.parse(Path(path).read_text())
    raw = doc.get("binaries")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str | None] = {}
    for key, value in raw.items():
        out[str(key)] = None if value is None else str(value)
    return out


def read_lockfile_meta(path: Path | str) -> dict[str, Any]:
    """Return the ``[hydromodpy]`` header section as a plain dict."""
    doc = tomlkit.parse(Path(path).read_text())
    raw = doc.get("hydromodpy")
    if not isinstance(raw, dict):
        return {}
    return {str(k): (None if v is None else v) for k, v in raw.items()}


def read_lockfile(path: Path | str) -> list[LockedArtifact]:
    """Load every legacy ``[[artefact]]`` block of the lockfile."""
    doc = tomlkit.parse(Path(path).read_text())
    out: list[LockedArtifact] = []
    for item in doc.get("artefact", []):
        out.append(
            LockedArtifact(
                variable=str(item["variable"]),
                source=str(item["source"]),
                station_id=(str(item["station_id"]) if "station_id" in item else None),
                file_path=str(item["file_path"]),
                sha256=str(item["sha256"]),
                file_mtime=(float(item["file_mtime"]) if "file_mtime" in item else None),
                size_bytes=(int(item["size_bytes"]) if "size_bytes" in item else None),
                fetched_at=str(item.get("fetched_at", "")),
            )
        )
    return out


__all__ = [
    "LOCKFILE_NAME",
    "LOCKFILE_VERSION",
    "LockMismatch",
    "LockedArtifact",
    "frozen_project_root",
    "is_frozen_mode",
    "project_lockfile_path",
    "read_lockfile",
    "read_lockfile_binaries",
    "read_lockfile_inputs",
    "read_lockfile_meta",
    "read_lockfile_schema_sha256",
    "resolve_lockfile_root",
    "set_frozen_mode",
    "sha256_of",
]
