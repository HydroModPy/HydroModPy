"""XDG-compliant path helpers and workspace path utilities.

Cache directory: binaries (solver downloads, http_cache).
State directory: index.duckdb, locks, audit.log.
Override env vars: HMP_CACHE_HOME, HMP_STATE_HOME, HMP_BIN.

Workspace layout constants and portable-path helpers also live here so
every layer (catalog writes, global index, CLI) shares a single source
of truth without depending on a higher layer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import platformdirs

if TYPE_CHECKING:
    from collections.abc import Iterable

_APP_NAME = "hydromodpy"

# Workspace filenames -------------------------------------------------------

CATALOG_FILENAME = "catalog.duckdb"
"""Per-project catalog DuckDB file living at ``<project>/catalog.duckdb``."""

PROJECT_TOML_FILENAME = "hydromodpy.toml"
"""Per-project HydroModPy config file living at ``<project>/hydromodpy.toml``."""

WORKSPACE_TOML_FILENAME = "workspace.toml"
"""Workspace-wide metadata file living at ``<workspace>/workspace.toml``."""

INDEX_FILENAME = "index.duckdb"
"""Machine-wide global index file living under ``state_dir()``."""

# Portable URI schemes ------------------------------------------------------

_LOCAL_SCHEMES: tuple[str, ...] = ("file",)
_CLOUD_SCHEMES: tuple[str, ...] = ("s3", "gs", "az", "abfs", "gcs")


def cache_dir() -> Path:
    """Return platform cache dir (HMP_CACHE_HOME override)."""
    override = os.environ.get("HMP_CACHE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_cache_dir(_APP_NAME))


def state_dir() -> Path:
    """Return platform state dir (HMP_STATE_HOME override)."""
    override = os.environ.get("HMP_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_state_dir(_APP_NAME))


def bin_dir(solver: str, version: str) -> Path:
    """Return solver binary install path (HMP_BIN override)."""
    override = os.environ.get("HMP_BIN")
    if override:
        return Path(override).expanduser().resolve() / solver / version
    return cache_dir() / "bin" / solver / version


# Workspace-relative path helpers ------------------------------------------


def to_workspace_relative(workspace: Path, target: Path) -> str:
    """Return ``target`` expressed as a POSIX path relative to ``workspace``.

    Both paths are resolved before comparison. Raises ``ValueError`` when
    ``target`` is not under ``workspace`` so callers never silently store
    an absolute path in a portable column.
    """
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        rel = tgt.relative_to(ws)
    except ValueError as exc:
        raise ValueError(f"{tgt} is not under workspace {ws}") from exc
    return rel.as_posix()


def from_workspace_relative(workspace: Path, rel: str) -> Path:
    """Return the absolute path of a workspace-relative POSIX string."""
    ws = Path(workspace).expanduser().resolve()
    return ws / rel


def is_under_workspace(workspace: Path, target: Path) -> bool:
    """Return True when ``target`` resolves under ``workspace``."""
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        tgt.relative_to(ws)
    except ValueError:
        return False
    return True


def encode_workspace_path(workspace: Path, target: Path) -> str:
    """Encode ``target`` as a portable string anchored at the workspace.

    Returns a workspace-relative POSIX path when ``target`` lives under
    ``workspace``. Otherwise tries ``cache://`` (under ``cache_dir()``) then
    ``state://`` (under ``state_dir()``). Raises ``ValueError`` when the
    target lies outside every supported anchor.
    """
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        return tgt.relative_to(ws).as_posix()
    except ValueError:
        pass
    cache_root = cache_dir().expanduser().resolve()
    try:
        return "cache://" + tgt.relative_to(cache_root).as_posix()
    except ValueError:
        pass
    state_root = state_dir().expanduser().resolve()
    try:
        return "state://" + tgt.relative_to(state_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Cannot encode {tgt} as a workspace-relative path. "
            f"Expected target under workspace={ws}, cache={cache_root} "
            f"or state={state_root}."
        ) from exc


def decode_workspace_path(workspace: Path, encoded: str) -> Path:
    """Decode an encoded portable path back to an absolute :class:`Path`."""
    ws = Path(workspace).expanduser().resolve()
    text = str(encoded)
    if text.startswith("cache://"):
        return cache_dir().expanduser().resolve() / text[len("cache://") :]
    if text.startswith("state://"):
        return state_dir().expanduser().resolve() / text[len("state://") :]
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve()
    return ws / candidate


# Portable workspace URI ----------------------------------------------------


def to_workspace_uri(path: Path) -> str:
    """Return the ``file://`` URI for a local workspace path."""
    resolved = Path(path).expanduser().resolve()
    return resolved.as_uri()


def resolve_workspace(uri: str) -> Path:
    """Resolve a portable ``workspace_uri`` to a local :class:`Path`.

    Supported schemes:
    - bare path (no scheme): treated as a local path.
    - ``file://``: parsed and returned as a :class:`Path`.
    - ``s3://`` / ``gs://`` / etc.: not implemented yet; raises
      :class:`NotImplementedError` until cloud workspaces ship (P15).
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if not scheme:
        return Path(uri).expanduser()
    if scheme in _LOCAL_SCHEMES:
        return Path(unquote(parsed.path)).expanduser()
    if scheme in _CLOUD_SCHEMES:
        raise NotImplementedError(
            f"Cloud workspace_uri {uri!r} is a v2.x stub. "
            "Install the cloud extra and a UPath backend to enable it."
        )
    raise ValueError(f"Unsupported workspace_uri scheme: {scheme!r}")


__all__: Iterable[str] = (
    "CATALOG_FILENAME",
    "INDEX_FILENAME",
    "PROJECT_TOML_FILENAME",
    "WORKSPACE_TOML_FILENAME",
    "bin_dir",
    "cache_dir",
    "decode_workspace_path",
    "encode_workspace_path",
    "from_workspace_relative",
    "is_under_workspace",
    "resolve_workspace",
    "state_dir",
    "to_workspace_relative",
    "to_workspace_uri",
)
