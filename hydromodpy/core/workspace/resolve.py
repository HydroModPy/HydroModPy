"""Workspace-root lookup, for runtime code and for the commands.

Solver-side code that needs to re-open a workspace catalog from a project
directory on disk (e.g. MODPATH replaying a previous solve) calls
:func:`locate_workspace_root`. The commands call :func:`find_workspace`,
:func:`find_data_workspace` and :func:`find_workspace_root`. These are
**read-only** lookups: they do not drive the strict binary resolution of
``WorkspaceConfig``.

Lookup strategy of :func:`locate_workspace_root` (first match wins):

1. ``HMP_WORKSPACE`` environment variable if it points at a
   directory.
2. ``<project_root>/../..`` when ``project_root.parent.name == "projects"``
   and the grand-grand-parent contains ``data/``.

Returns ``None`` when no workspace can be found - callers fall back to
the project_root directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from hydromodpy.core.state.layout import is_workspace_root


def locate_workspace_root(project_root: Path | str) -> Path | None:
    """Best-effort lookup, returning ``None`` on miss."""
    env = os.environ.get("HMP_WORKSPACE")
    if env:
        env_path = Path(env).expanduser()
        if env_path.is_dir():
            return env_path.resolve()

    resolved = Path(project_root).expanduser().resolve()
    if resolved.parent.name == "projects":
        candidate = resolved.parent.parent
        if (candidate / "data").is_dir():
            return candidate
    return None


def find_workspace_root(project_dir: Path) -> Path:
    """Walk up from ``project_dir`` to find the shared data workspace."""
    start = project_dir.resolve()
    if start.name == "projects" and start.parent.is_dir():
        return start.parent
    for parent in [start] + list(start.parents):
        if parent.parent.name == "projects":
            return parent.parent.parent
        if (parent / "projects").is_dir() or (parent / "data").is_dir():
            return parent
    return start


def find_data_workspace(start: Path) -> Path | None:
    """Walk up from ``start`` to find a workspace root (has a ``data/`` folder)."""
    for parent in [start] + list(start.parents):
        if not parent.is_dir():
            continue
        if (parent / "data").is_dir() and (
            (parent / "projects").is_dir() or (parent / "workspace.toml").exists()
        ):
            return parent
    return None


def find_workspace(workspace_arg: str | None) -> Path | None:
    """Return the workspace named by ``-w``, by ``HMP_WORKSPACE``, or above the cwd.

    A named project directory resolves to the workspace that holds it; a named
    directory that carries ``data/``, ``projects/`` or ``workspace.toml`` is
    the workspace. Returns ``None`` when nothing answers: there is no default
    folder such as ``~/hydromodpy``.
    """
    named = workspace_arg or os.environ.get("HMP_WORKSPACE")
    start = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not start.is_dir():
        return None
    found = find_data_workspace(start)
    if found is None and (is_workspace_root(start) or (named and (start / "data").is_dir())):
        found = start
    return found
