"""Resolution of the workspace, the project and the TOML file a command is given."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hydromodpy.cli.exit_codes import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    refuse,
)

# ---------------------------------------------------------------------------
# Workspace / project discovery
# ---------------------------------------------------------------------------


def resolve_workspace(workspace_arg: str | None) -> Path:
    """Return :func:`~hydromodpy.core.workspace.resolve.find_workspace`, or stop with :data:`EXIT_NOT_FOUND` naming ``-w``."""
    from hydromodpy.core.workspace.resolve import find_workspace
    from hydromodpy.core.workspace.workspace_toml import refuse_a_newer_workspace

    found = find_workspace(workspace_arg)
    if found is not None:
        refuse_a_newer_workspace(found)
        return found
    named = workspace_arg or os.environ.get("HMP_WORKSPACE")
    start = Path(named).expanduser().resolve() if named else Path.cwd().resolve()
    if not start.is_dir():
        refuse(
            f"Workspace {start} does not exist. Run 'hmp workspace init {start}' first.",
            EXIT_NOT_FOUND,
        )
    refuse(
        f"No HydroModPy workspace at or above {start}. Name one with -w, "
        "or run 'hmp workspace init' first.",
        EXIT_NOT_FOUND,
    )


def resolve_project(workspace_arg: str | None) -> Path:
    """Return the project named by ``-w``, or the one that holds the cwd.

    The project is the directory that carries ``project.toml`` (or an index).
    Without one, the command stops with :data:`EXIT_NOT_FOUND`.
    """
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, is_project_root
    from hydromodpy.core.state.result_dirs import resolve_project_root

    start = Path(workspace_arg).expanduser().resolve() if workspace_arg else Path.cwd().resolve()
    root = resolve_project_root(start)
    if not is_project_root(root):
        refuse(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}. Name the project with -w.",
            EXIT_NOT_FOUND,
        )
    return root


def project_root_of(args: Any) -> Path:
    """Return the project root ``-w`` names, or the one around the current directory.

    Nothing is checked: a verb that reads an index refuses when it finds none.
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root

    named = getattr(args, "workspace", None)
    return resolve_project_root(Path(named or Path.cwd()).expanduser().resolve())


def base_named_by_w(workspace_arg: str | None) -> Path | None:
    """Return the project ``-w`` names, the base of a TOML verb, or ``None`` without ``-w``.

    A verb passes it to the loader as an argument. Without ``-w`` the base is the
    one the file gives: the project root above it.
    """
    return resolve_project(workspace_arg) if workspace_arg else None


def resolve_project_ref(workspace_arg: str | None, ref: str | None) -> Path:
    """Return the project a reference names: a path is read as a path, a bare name under projects/.

    A path is ``.``, ``..``, anything with a slash or an absolute path: the
    project at or above it. Nothing found stops with :data:`EXIT_NOT_FOUND`.
    """
    if ref is None:
        return resolve_project(workspace_arg)
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, PROJECTS_DIRNAME

    if not _is_path_ref(ref):
        project_dir = resolve_workspace(workspace_arg) / PROJECTS_DIRNAME / ref
        if not project_dir.is_dir():
            refuse(f"No such project: {project_dir}", EXIT_NOT_FOUND)
        return project_dir
    from hydromodpy.core.state.result_dirs import resolve_project_root

    start = Path(ref).expanduser().resolve()
    root = resolve_project_root(start)
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        refuse(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}: name a project directory, "
            "or a project name under projects/ of the workspace.",
            EXIT_NOT_FOUND,
        )
    return root


def _is_path_ref(ref: str) -> bool:
    return ref in (".", "..") or "/" in ref or Path(ref).expanduser().is_absolute()


def toml_target(config: str | Path) -> Path:
    """Return the TOML file a verb was given, or stop: missing is 10, another suffix is 14."""
    target = Path(config).expanduser().resolve()
    if not target.is_file():
        refuse(f"File not found: {target}", EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        refuse(f"Expected a .toml file, got: {target.suffix}", EXIT_CONFIG)
    return target


__all__ = (
    "base_named_by_w",
    "project_root_of",
    "resolve_project",
    "resolve_project_ref",
    "resolve_workspace",
    "toml_target",
)
