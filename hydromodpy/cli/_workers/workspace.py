"""Private worker helpers for ``hmp workspace`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
    """Register a workspace ``catalog.duckdb`` in the global index.

    Returns the assigned ``workspace_id``.
    """
    from hydromodpy.core.state.global_index import GlobalIndex
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.core.state.paths import resolve_workspace as _resolve

    local = _resolve(uri)
    catalog = Path(local) / CATALOG_FILENAME
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
    """Drop registrations whose ``catalog.duckdb`` is missing."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        return gi.prune()


def clean_workspace(
    workspace: Any,
    *,
    groups: set[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Remove generated workspace artefacts.

    ``groups`` selects which artefact families to remove. Default is empty
    (the caller is expected to pass at least one of ``results``,
    ``data_cache``, ``runtime``, ``exports``, ``scratch``, ``figures``, or
    use ``{"all"}``).
    """
    import shutil

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    start = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root = find_workspace_root(start)
    if not workspace_root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace_root}")

    selected = set(groups or set())
    if "all" in selected or selected == {"all"}:
        selected = {"results", "data_cache", "runtime", "exports", "scratch", "figures"}
    if not selected:
        raise ValueError("Select at least one cleanup group, or pass groups={'all'}.")

    targets: list[Path] = []
    if "results" in selected:
        targets.extend(
            [
                workspace_root / CATALOG_FILENAME,
                workspace_root / f"{CATALOG_FILENAME}.wal",
                workspace_root / "simulations",
            ]
        )
        for project_dir in sorted(workspace_root.glob("projects/*")):
            if project_dir.is_dir():
                targets.extend(
                    [
                        project_dir / CATALOG_FILENAME,
                        project_dir / f"{CATALOG_FILENAME}.wal",
                        project_dir / "simulations",
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
    if "exports" in selected:
        targets.append(workspace_root / "exports")
    if "scratch" in selected:
        targets.extend(sorted(workspace_root.glob("projects/*/.solver_scratch")))
        targets.append(workspace_root / ".solver_scratch")
    if "figures" in selected:
        targets.extend(sorted(workspace_root.glob("projects/*/figures")))

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
