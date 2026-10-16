"""Private worker helpers for ``hmp project`` actions."""

from __future__ import annotations

from pathlib import Path


def create_project(name: str, *, workspace: Path) -> Path:
    """Scaffold ``<workspace>/projects/<name>`` and return it.

    Raises :class:`FileNotFoundError` when *workspace* is not a scaffolded
    HydroModPy workspace.
    """
    from hydromodpy.data.workspace.scaffold import create_project as _create

    workspace_root = Path(workspace).expanduser().resolve()
    layout_ok = (workspace_root / "data").is_dir() or (workspace_root / "projects").is_dir()
    if not layout_ok:
        raise FileNotFoundError(
            f"{workspace_root} is not a HydroModPy workspace; run 'hmp workspace init' first"
        )
    return _create(workspace_root, name)


def list_projects(workspace: Path) -> list[dict]:
    """List the projects of *workspace*, one dict each.

    Each dict carries ``name``, ``path``, ``has_project_toml`` and ``run_tomls``.
    """
    from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME

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


def delete_project(name: str, *, workspace: Path, force: bool = False) -> dict:
    """Delete ``<workspace>/projects/<name>`` and everything under it.

    Returns a dict with ``path`` and ``bytes_freed``. Raises if the project
    does not exist. ``force`` is informational only (the CLI layer enforces it).
    """
    import shutil

    project_dir = Path(workspace).expanduser().resolve() / "projects" / name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    bytes_freed = 0
    for child in project_dir.rglob("*"):
        try:
            if child.is_file():
                bytes_freed += int(child.stat().st_size)
        except OSError:
            continue
    shutil.rmtree(project_dir)
    return {"path": str(project_dir), "bytes_freed": bytes_freed, "force": force}


def sites_project_root(target: str | Path) -> Path:
    """Return the root of the ``[sites]`` project *target* names.

    *target* is the project folder, its ``project.toml`` or a folder inside
    it. Raises :class:`FileNotFoundError` when no ``project.toml`` sits at or
    above it.
    """
    from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, resolve_project_root

    path = Path(target).expanduser().resolve()
    start = path.parent if path.is_file() else path
    root = resolve_project_root(start)
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise FileNotFoundError(f"no {PROJECT_MARKER_FILENAME} at or above {path}")
    return root
