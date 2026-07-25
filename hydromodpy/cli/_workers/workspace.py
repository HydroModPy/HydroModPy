"""Private worker helpers for ``hmp workspace`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CLEAN_GROUPS: tuple[str, ...] = (
    "results",
    "data_cache",
    "runtime",
    "share",
    "scratch",
    "figures",
)
"""Artefact families ``clean_workspace`` knows how to remove."""


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
    from hydromodpy.core.state.global_index import auto_register_workspace
    from hydromodpy.core.workspace.workspace_toml import write_workspace_toml
    from hydromodpy.data.scaffold import DEFAULT_ROOT, scaffold

    target = Path(path).expanduser().resolve() if path else DEFAULT_ROOT
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"Workspace already initialized at {target}. Re-run with force=True to reuse it."
        )
    result = scaffold(target)
    workspace_toml = write_workspace_toml(
        result,
        project_name=project_name or result.name,
        creator_name=creator_name or "",
        creator_email=creator_email or "",
        force=force,
    )
    auto_register_workspace(result, label=project_name or result.name)
    return {"path": str(result), "workspace_toml": str(workspace_toml)}


def list_workspaces() -> Any:
    """List workspaces registered in the machine-wide global index."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex(read_only=True) as gi:
        return gi.list_workspaces()


def register_workspace(uri: str, *, label: str | None = None) -> str:
    """Register a workspace index database in the global index.

    Returns the assigned ``workspace_id``.
    """
    from hydromodpy.core.state.global_index import GlobalIndex
    from hydromodpy.core.state.paths import CATALOG_FILENAME, catalog_path_for
    from hydromodpy.core.state.paths import resolve_workspace as _resolve

    local = _resolve(uri)
    catalog = catalog_path_for(Path(local))
    if not catalog.is_file():
        raise FileNotFoundError(f"Workspace {uri!r} has no {CATALOG_FILENAME} at {catalog}.")
    with GlobalIndex() as gi:
        return gi.register_workspace(uri, label=label)


def search_workspaces(term: str, *, limit: int = 20) -> Any:
    """Full-text search across registered workspaces."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex(read_only=True) as gi:
        df = gi.search(term)
    if df is None or df.empty:
        return df
    return df.head(limit)


def forget_workspace(workspace_id: str) -> None:
    """Drop a workspace registration from the global index."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        gi.forget(workspace_id)


def prune_workspaces() -> list[str]:
    """Drop registrations whose index database is missing."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        return gi.prune()


def clean_workspace(
    workspace: Any,
    *,
    groups: set[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Remove generated project artefacts.

    ``groups`` selects which artefact families to remove: ``results`` (the
    index database and the ``runs/`` tree), ``data_cache``, ``runtime``
    (``.hmp/``), ``share`` (the published tree), ``scratch``
    (``.hmp/scratch``) and ``figures`` (``share/figures``). Default is empty
    (the caller passes at least one group, or ``{"all"}``).
    """
    import shutil

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import (
        CATALOG_FILENAME,
        catalog_path_for,
        runs_dir_for,
        scratch_dir_for,
        share_dir_for,
    )

    start = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root = find_workspace_root(start)
    if not workspace_root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace_root}")

    selected = set(groups or set())
    if "all" in selected or selected == {"all"}:
        selected = set(CLEAN_GROUPS)
    if not selected:
        raise ValueError("Select at least one cleanup group, or pass groups={'all'}.")

    targets: list[Path] = []
    if "results" in selected:
        targets.extend(
            [
                catalog_path_for(workspace_root),
                catalog_path_for(workspace_root).with_name(f"{CATALOG_FILENAME}.wal"),
                runs_dir_for(workspace_root),
            ]
        )
        for project_dir in sorted(workspace_root.glob("projects/*")):
            if project_dir.is_dir():
                targets.extend(
                    [
                        catalog_path_for(project_dir),
                        catalog_path_for(project_dir).with_name(f"{CATALOG_FILENAME}.wal"),
                        runs_dir_for(project_dir),
                    ]
                )
    if "data_cache" in selected:
        targets.extend(
            [
                workspace_root / "data" / "cache.duckdb",
                workspace_root / "data" / "cache.duckdb.wal",
                workspace_root / "data" / "blobs",
            ]
        )
    if "runtime" in selected:
        targets.append(workspace_root / ".hmp")
    if "share" in selected:
        targets.append(share_dir_for(workspace_root))
        targets.extend(share_dir_for(p) for p in sorted(workspace_root.glob("projects/*")))
    if "scratch" in selected:
        targets.extend(scratch_dir_for(p) for p in sorted(workspace_root.glob("projects/*")))
        targets.append(scratch_dir_for(workspace_root))
    if "figures" in selected:
        targets.extend(
            share_dir_for(p) / "figures" for p in sorted(workspace_root.glob("projects/*"))
        )
        targets.append(share_dir_for(workspace_root) / "figures")

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
