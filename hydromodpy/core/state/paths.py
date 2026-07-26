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

from hydromodpy.core.exceptions import ConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable

_APP_NAME = "hydromodpy"

# Project layout -----------------------------------------------------------
#
# A project root is::
#
#     project.toml            configuration, and the marker of the root
#     configs/                config variants (user-managed, never created)
#     runs/<name>/            one directory per run, named after the run
#     sessions/<name>/        calibration and spin-up sessions
#     share/                  on-demand exports, reports and portable packages
#     .hmp/                   disposable internals (index, trash, scratch, ...)
#
# Every directory name of that layout is declared here so no layer has to
# hard-code a literal. The names of the files *inside* one run directory
# belong to the result-storage contract
# (:mod:`hydromodpy.results.storage.contract`).

PROJECT_MARKER_FILENAME = "project.toml"
"""The project configuration file, and the marker of a project root.

One file plays both roles: ``<project>/project.toml`` holds the shared
settings of the project and anchors :func:`resolve_project_root`. Creating a
project writes it, so a scaffolded project is anchored from its first day.
"""

CONFIGS_DIRNAME = "configs"
"""Reserved sub-directory holding the config variants of a project."""

RUNS_DIRNAME = "runs"
"""Directory holding one sub-directory per run at ``<project>/runs/<name>``."""

SESSIONS_DIRNAME = "sessions"
"""Directory holding calibration and spin-up sessions."""

SHARE_DIRNAME = "share"
"""Directory holding on-demand exports and portable packages."""

REPORTS_DIRNAME = "reports"
"""Report sub-directory of :data:`SHARE_DIRNAME`."""

INTERNAL_DIRNAME = ".hmp"
"""Disposable internals: index database, trash, scratch, logs, cache."""

CATALOG_FILENAME = "index.duckdb"
"""Project index database living at ``<project>/.hmp/index.duckdb``."""

WORKSPACE_TOML_FILENAME = "workspace.toml"
"""Workspace-wide metadata file living at ``<workspace>/workspace.toml``."""

INDEX_FILENAME = "index.duckdb"
"""Machine-wide global index file living under ``state_dir()``."""


def internal_dir(project_root: Path) -> Path:
    """Return ``<project>/.hmp``, the disposable internals directory."""
    return Path(project_root) / INTERNAL_DIRNAME


def catalog_path_for(project_root: Path) -> Path:
    """Return the project index database ``<project>/.hmp/index.duckdb``."""
    return internal_dir(project_root) / CATALOG_FILENAME


def runs_dir_for(project_root: Path) -> Path:
    """Return ``<project>/runs``, the parent of every run directory."""
    return Path(project_root) / RUNS_DIRNAME


def share_dir_for(project_root: Path) -> Path:
    """Return ``<project>/share``, where on-demand outputs are published."""
    return Path(project_root) / SHARE_DIRNAME


def reports_dir_for(project_root: Path) -> Path:
    """Return ``<project>/share/reports``."""
    return share_dir_for(project_root) / REPORTS_DIRNAME


def scratch_dir_for(output_root: Path) -> Path:
    """Return ``<root>/.hmp/scratch``, the solver working directory."""
    return internal_dir(output_root) / "scratch"


def running_sidecar_dir(workspace: Path) -> Path:
    """Directory of live-run heartbeat sidecars under a project root.

    A solving run keeps ``<workspace>/.hmp/running/<id8>.json`` fresh so
    ``hmp catalog watch`` and ``hmp catalog gc`` read liveness from a file, never the DuckDB
    catalog (which a live solve holds locked).
    """
    return internal_dir(workspace) / "running"


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


def resolve_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory holding ``project.toml``.

    The anchor is the project config file, never a database file: the catalog
    is a rebuildable index and may be absent. Without a marker the starting
    directory is the root, so a flat project directory still resolves. A
    ``configs/`` directory is the exception: anchoring there would scatter the
    project outputs under the sub-directory, so it raises instead.
    """
    base = Path(start)
    for parent in [base, *base.parents]:
        if (parent / PROJECT_MARKER_FILENAME).is_file():
            return parent
    if base.name == CONFIGS_DIRNAME:
        raise ConfigError(
            f"No {PROJECT_MARKER_FILENAME} found above {base}. A config stored in "
            f"{CONFIGS_DIRNAME}/ cannot anchor a project root: add "
            f"{PROJECT_MARKER_FILENAME} to {base.parent}."
        )
    return base


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
    "CONFIGS_DIRNAME",
    "INDEX_FILENAME",
    "INTERNAL_DIRNAME",
    "PROJECT_MARKER_FILENAME",
    "REPORTS_DIRNAME",
    "RUNS_DIRNAME",
    "SESSIONS_DIRNAME",
    "SHARE_DIRNAME",
    "WORKSPACE_TOML_FILENAME",
    "cache_dir",
    "catalog_path_for",
    "decode_workspace_path",
    "encode_workspace_path",
    "from_workspace_relative",
    "internal_dir",
    "is_under_workspace",
    "reports_dir_for",
    "resolve_project_root",
    "resolve_workspace",
    "running_sidecar_dir",
    "running_sidecar_path",
    "runs_dir_for",
    "scratch_dir_for",
    "share_dir_for",
    "state_dir",
    "to_workspace_relative",
    "to_workspace_uri",
)
