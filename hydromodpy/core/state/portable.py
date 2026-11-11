"""Portable paths: platform cache and state folders, workspace-relative strings, root URIs.

Cache directory: binaries (solver downloads, http_cache).
State directory: machine-wide state that no project owns.
Override env vars: HMP_CACHE_HOME, HMP_STATE_HOME.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import platformdirs
from upath import UPath

_APP_NAME = "hydromodpy"


def display_path(path: Path | str) -> str:
    """Return *path* as the shortest spelling a reader can still follow.

    Console lines carry absolute paths that are mostly the same prefix
    repeated. Relative to the current directory when the path sits under
    it, with forward slashes on every OS as a TOML names it; absolute
    otherwise, in the platform's own spelling.
    """
    resolved = Path(path)
    try:
        return resolved.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(resolved)


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


def resolve_workspace(uri: str | Path | UPath) -> Path:
    """Resolve a portable root URI to a local :class:`Path`.

    The URI may point at a workspace root or a project root: this helper only
    turns a portable string into a filesystem path and says nothing about the
    granularity of what it points at. Use :func:`project_roots_under` for that.

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
        f"root URI {text!r} uses scheme {scheme!r} which is not supported "
        "in this release. Use a local path or a file:// URI."
    )


__all__ = (
    "cache_dir",
    "decode_workspace_path",
    "display_path",
    "encode_workspace_path",
    "resolve_workspace",
    "state_dir",
    "to_workspace_relative",
)
