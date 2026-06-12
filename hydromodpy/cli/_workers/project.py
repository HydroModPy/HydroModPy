"""Private worker helpers for ``hmp project`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def create_project(name: str, *, workspace: Any = None) -> Path:
    """Scaffold a new project directory inside a workspace.

    Parameters
    ----------
    name
        Project name (created under ``<workspace>/projects/<name>``).
    workspace
        Workspace root. Defaults to :data:`hydromodpy.data.scaffold.DEFAULT_ROOT`.

    Returns
    -------
    pathlib.Path
        Path to the new project directory.

    Raises
    ------
    FileNotFoundError
        If ``workspace`` does not look like a scaffolded HydroModPy workspace.
    """
    from hydromodpy.data.scaffold import DEFAULT_ROOT
    from hydromodpy.data.scaffold import create_project as _create

    workspace_root = Path(workspace).expanduser().resolve() if workspace else DEFAULT_ROOT
    layout_ok = (workspace_root / "data").is_dir() or (workspace_root / "projects").is_dir()
    if not layout_ok:
        raise FileNotFoundError(
            f"{workspace_root} is not a HydroModPy workspace; run 'hmp workspace init' first"
        )
    return _create(workspace_root, name)


def list_projects(workspace: Any = None) -> list[dict]:
    """List projects inside a workspace.

    Returns a list of dicts (one per project) with ``name``, ``path``,
    ``has_project_toml``, ``run_tomls``.
    """
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import PROJECT_TOML_FILENAME
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

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
                "has_project_toml": (project_dir / PROJECT_TOML_FILENAME).is_file(),
                "run_tomls": [p.name for p in project_dir.glob("run_*.toml")],
            }
        )
    return out


def show_project(name: str, *, workspace: Any = None) -> dict:
    """Return a summary dict for one project (TOMLs + catalog stats)."""
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME, PROJECT_TOML_FILENAME
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

    project_dir = workspace_root / "projects" / name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    payload: dict = {
        "name": name,
        "path": str(project_dir),
        "has_project_toml": (project_dir / PROJECT_TOML_FILENAME).is_file(),
        "run_tomls": [p.name for p in sorted(project_dir.glob("run_*.toml"))],
        "simulations": [],
    }
    db_path = project_dir / CATALOG_FILENAME
    if db_path.exists():
        from hydromodpy.results.catalog import Catalog, short_id

        try:
            with Catalog(project_dir) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
            payload["simulations"] = [
                {
                    "sim_id": str(row["sim_id"]),
                    "short_id": short_id(str(row["sim_id"])),
                    "name": row.get("name", "") or "(no name)",
                    "solver": row.get("solver", ""),
                    "status": row.get("status", ""),
                }
                for _, row in sims.iterrows()
            ]
        except Exception as exc:  # pragma: no cover - defensive
            payload["catalog_error"] = str(exc)
    return payload


def delete_project(name: str, *, workspace: Any = None, force: bool = False) -> dict:
    """Delete a project directory (catalog + Zarr + Parquet).

    Returns a dict with ``path``, ``bytes_freed``. Raises if the project does
    not exist. ``force`` is informational only (the CLI layer enforces it).
    """
    import os
    import shutil

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

    project_dir = workspace_root / "projects" / name
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
