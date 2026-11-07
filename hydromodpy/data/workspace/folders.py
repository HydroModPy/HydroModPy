"""Folders of a workspace and of its projects: create, list, delete, clean.

The verbs of ``hmp workspace init`` and ``clean`` and of ``hmp project new``,
``list`` and ``delete``. They read only ``core`` and the scaffold of this
package.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hydromodpy.core.io.filesystem import path_size
from hydromodpy.core.state.layout import (
    DATA_CACHE_FILENAME,
    PROJECT_MARKER_FILENAME,
    data_cache_path_for,
)
from hydromodpy.core.state.scratch import scratch_root_for
from hydromodpy.core.workspace.resolve import find_workspace_root
from hydromodpy.core.workspace.workspace_toml import write_workspace_toml
from hydromodpy.data.workspace.scaffold import DEFAULT_ROOT, scaffold
from hydromodpy.data.workspace.scaffold import create_project as scaffold_project


def create_project(name: str, *, workspace: Path) -> Path:
    """Scaffold ``<workspace>/projects/<name>`` and return it.

    Raises :class:`FileNotFoundError` when *workspace* is not a scaffolded
    HydroModPy workspace.
    """
    workspace_root = Path(workspace).expanduser().resolve()
    layout_ok = (workspace_root / "data").is_dir() or (workspace_root / "projects").is_dir()
    if not layout_ok:
        raise FileNotFoundError(
            f"{workspace_root} is not a HydroModPy workspace; run 'hmp workspace init' first"
        )
    return scaffold_project(workspace_root, name)


def list_projects(workspace: Path) -> list[dict]:
    """List the projects of *workspace*, one dict each.

    Each dict carries ``name``, ``path``, ``has_project_toml`` and ``run_tomls``.
    """
    workspace_root = Path(workspace).expanduser().resolve()
    projects_dir = workspace_root / "projects"
    if not projects_dir.is_dir():
        raise FileNotFoundError(f"No projects/ directory in {workspace_root}")

    out: list[dict] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        out.append(
            {
                "name": project_dir.name,
                "path": str(project_dir),
                "has_project_toml": (project_dir / PROJECT_MARKER_FILENAME).is_file(),
                "run_tomls": [p.name for p in project_dir.glob("run_*.toml")],
            }
        )
    return out


def delete_project(name: str, *, workspace: Path) -> dict:
    """Delete ``<workspace>/projects/<name>`` and everything under it.

    Returns a dict with ``path`` and ``bytes_freed``. Raises if the project
    does not exist. The command asks before it calls this.
    """
    project_dir = Path(workspace).expanduser().resolve() / "projects" / name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    bytes_freed = path_size(project_dir)
    shutil.rmtree(project_dir)
    return {"path": str(project_dir), "bytes_freed": bytes_freed}


CLEAN_GROUPS: tuple[str, ...] = (
    "data_cache",
    "runtime",
    "scratch",
)
"""Rebuildable families ``clean_workspace`` removes; results go to the trash, never here."""


def init_workspace(
    path: Any = None,
    *,
    force: bool = False,
    project_name: str | None = None,
    creator_name: str | None = None,
    creator_email: str | None = None,
) -> dict:
    """Scaffold a HydroModPy workspace (data + projects + ``workspace.toml``).

    Returns a dict with ``path`` and ``workspace_toml``.
    """
    target = Path(path).expanduser().resolve() if path else DEFAULT_ROOT
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"Workspace already initialized at {target}. Pass --force to reuse it."
        )
    result = scaffold(target)
    workspace_toml = write_workspace_toml(
        result,
        project_name=project_name or result.name,
        creator_name=creator_name or "",
        creator_email=creator_email or "",
        force=force,
    )
    return {"path": str(result), "workspace_toml": str(workspace_toml)}


def clean_workspace(
    workspace: Any,
    *,
    groups: set[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Remove what a workspace can rebuild.

    ``groups`` selects which families to remove: ``data_cache``, ``runtime``
    (``.hmp/``) and ``scratch`` (``.hmp/scratch``). Runs and sessions are
    never removed here: ``hmp workspace clean --results`` moves them to the
    trash. Default is empty (the caller passes at least one group, or
    ``{"all"}``).
    """
    start = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root = find_workspace_root(start)
    if not workspace_root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace_root}")

    selected = set(groups or set())
    if "all" in selected or selected == {"all"}:
        selected = set(CLEAN_GROUPS)
    if not selected:
        raise ValueError("Select at least one cleanup group, or pass groups={'all'}.")

    unknown = selected - set(CLEAN_GROUPS)
    if unknown:
        raise ValueError(f"Unknown cleanup group(s): {', '.join(sorted(unknown))}.")

    targets: list[Path] = []
    if "data_cache" in selected:
        targets.extend(
            [
                data_cache_path_for(workspace_root / "data"),
                data_cache_path_for(workspace_root / "data").with_name(
                    f"{DATA_CACHE_FILENAME}.wal"
                ),
                workspace_root / "data" / "blobs",
            ]
        )
    if "runtime" in selected:
        targets.append(workspace_root / ".hmp")
    if "scratch" in selected:
        targets.extend(scratch_root_for(p) for p in sorted(workspace_root.glob("projects/*")))
        # The workspace-level scratch is always the one under .hmp/: the machine scratch of
        # HMP_SCRATCH_ROOT holds only project folders, never one named after the workspace.
        targets.append(workspace_root / ".hmp" / "scratch")

    seen: set[Path] = set()
    unique: list[Path] = []
    for target in targets:
        resolved = target.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(target)
    existing = [t for t in unique if t.exists() or t.is_symlink()]

    removed: list[str] = []
    if not dry_run:
        for target in existing:
            resolved_workspace = workspace_root.resolve()
            resolved_target = target.resolve(strict=False)
            if (
                resolved_target == resolved_workspace
                or resolved_workspace not in resolved_target.parents
            ):
                raise ValueError(f"Refusing to delete path outside workspace: {target}")
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            removed.append(str(target))

    return {
        "workspace": str(workspace_root),
        "candidates": [str(t) for t in existing],
        "removed": removed,
        "dry_run": dry_run,
    }
