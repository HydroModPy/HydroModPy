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
from urllib.parse import urlparse
from urllib.request import url2pathname

import platformdirs
from upath import UPath

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


def running_sidecar_dir(workspace: Path) -> Path:
    """Directory of live-run heartbeat sidecars under a project root.

    A solving run keeps ``<workspace>/.hmp/running/<id8>.json`` fresh so
    ``hmp watch`` and ``gc`` can read liveness from a file, never the DuckDB
    catalog (which a live solve holds locked).
    """
    return Path(workspace) / ".hmp" / "running"


def running_sidecar_path(workspace: Path, sim_id: str) -> Path:
    """Heartbeat sidecar path for a run, keyed by its first 8 hex digits."""
    id8 = str(sim_id).replace("-", "")[:8]
    return running_sidecar_dir(workspace) / f"{id8}.json"


# Portable URI schemes ------------------------------------------------------

_LOCAL_SCHEMES: tuple[str, ...] = ("file",)


def cache_dir() -> Path | UPath:
    """Return platform cache dir (HMP_CACHE_HOME override)."""
    override = os.environ.get("HMP_CACHE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_cache_dir(_APP_NAME))


def state_dir() -> Path | UPath:
    """Return platform state dir (HMP_STATE_HOME override)."""
    override = os.environ.get("HMP_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_state_dir(_APP_NAME))


# Workspace-relative path helpers ------------------------------------------


def find_catalog_root(project_dir: Path) -> Path:
    """Walk up from ``project_dir`` to find a project-local catalog."""
    for parent in [project_dir] + list(project_dir.parents):
        if (parent / CATALOG_FILENAME).exists():
            return parent
    return project_dir


def to_workspace_relative(workspace: Path | UPath, target: Path | UPath) -> str:
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


def from_workspace_relative(workspace: Path | UPath, rel: str) -> Path:
    """Return the absolute path of a workspace-relative POSIX string."""
    ws = Path(workspace).expanduser().resolve()
    return ws / rel


def is_under_workspace(workspace: Path | UPath, target: Path | UPath) -> bool:
    """Return True when ``target`` resolves under ``workspace``."""
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        tgt.relative_to(ws)
    except ValueError:
        return False
    return True


def encode_workspace_path(workspace: Path | UPath, target: Path | UPath) -> str:
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


def decode_workspace_path(workspace: Path | UPath, encoded: str) -> Path:
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


def to_workspace_uri(path: Path | UPath) -> str:
    """Return the ``file://`` URI for a local workspace path."""
    resolved = Path(path).expanduser().resolve()
    return resolved.as_uri()


def resolve_workspace(uri: str | Path | UPath) -> Path:
    """Resolve a portable ``workspace_uri`` to a local :class:`Path`.

    The argument is widened to ``str | Path | UPath`` so callers can
    pass either a raw URI, a :class:`pathlib.Path`, or a
    :class:`upath.UPath` instance. Non-local URIs are accepted at the
    type level but rejected at runtime: this release only resolves
    workspaces on the local filesystem.

    Supported schemes:
    - bare path (no scheme): treated as a local path.
    - ``file://``: parsed and returned as a :class:`Path`.
    - any other scheme: raises :class:`NotImplementedError` with the
      offending URI.
    """
    text = str(uri)
    candidate = Path(text).expanduser()
    if os.name == "nt" and candidate.drive:
        return candidate
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if not scheme:
        return candidate
    if scheme in _LOCAL_SCHEMES:
        path_text = parsed.path
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path_text = f"//{parsed.netloc}{path_text}"
        return Path(url2pathname(path_text)).expanduser()
    raise NotImplementedError(
        f"workspace_uri {text!r} uses scheme {scheme!r} which is not supported "
        "in this release. Use a local path or a file:// URI."
    )


__all__: Iterable[str] = (
    "CATALOG_FILENAME",
    "INDEX_FILENAME",
    "PROJECT_TOML_FILENAME",
    "WORKSPACE_TOML_FILENAME",
    "cache_dir",
    "decode_workspace_path",
    "encode_workspace_path",
    "find_catalog_root",
    "from_workspace_relative",
    "is_under_workspace",
    "resolve_workspace",
    "running_sidecar_dir",
    "running_sidecar_path",
    "state_dir",
    "to_workspace_relative",
    "to_workspace_uri",
)
