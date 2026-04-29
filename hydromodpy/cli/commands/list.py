"""``hmp list`` - list projects or runs in a workspace.

Workspace discovery mirrors ``hmp display --list``:

1. ``--workspace`` flag, if provided.
2. ``HYDROMODPY_WORKSPACE`` environment variable.
3. Walk up from the current directory looking for ``hydromodpy.duckdb``.
4. Fall back to :data:`hydromodpy.data.scaffold.DEFAULT_ROOT` (``~/hydromodpy``).

This way a run registered by ``hmp run`` (which uses the same walk-up rule)
is always visible to ``hmp list`` from anywhere inside the project tree.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root

NAME = "list"
HELP = "List projects or runs in a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "project",
        nargs="?",
        help="Project name to list runs for (omit for project listing)",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    """Resolve the workspace root the same way ``hmp display --list`` does."""
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()

    ws_override = os.environ.get("HYDROMODPY_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    found = find_workspace_root(start)
    if (found / "hydromodpy.duckdb").exists():
        return found
    return Path(DEFAULT_ROOT).expanduser().resolve()


def run(args: argparse.Namespace) -> None:
    workspace_root = _resolve_workspace(args.workspace)
    projects_dir = workspace_root / "projects"
    db_path = workspace_root / "hydromodpy.duckdb"

    if args.project:
        if not db_path.exists():
            print(f"No hydromodpy.duckdb in {workspace_root}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        try:
            from hydromodpy.results.catalog import (
                SimulationCatalog,
                short_id,
            )

            with SimulationCatalog(workspace_root) as catalog:
                sims = catalog.list_simulations(
                    project=args.project,
                    order_by="created_at DESC",
                )
                if sims.empty:
                    print(f"  No simulations recorded in {args.project}")
                    return
                for _, row in sims.iterrows():
                    sim_id = str(row["sim_id"])
                    name = row.get("name", "")
                    solver = row.get("solver", "")
                    status = row.get("status", "")
                    dur = row.get("duration_s")
                    label = name or "(no name)"
                    dur_str = f" {dur:.1f}s" if dur else ""
                    print(
                        f"  {label}  [{short_id(sim_id)}]  "
                        f"solver={solver}  status={status}{dur_str}"
                    )
        except Exception as exc:
            print(f"  Error reading hydromodpy.duckdb: {exc}", file=sys.stderr)
        return

    # No project arg: list project directories, then runs from the catalog.
    print(f"# workspace: {workspace_root}")

    if projects_dir.is_dir():
        print("# projects/ (filesystem):")
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            has_project_toml = (project_dir / "project.toml").exists()
            run_tomls = list(project_dir.glob("run_*.toml"))
            details = []
            if has_project_toml:
                details.append("project.toml")
            if run_tomls:
                details.append(f"{len(run_tomls)} run(s)")
            suffix = f"  [{', '.join(details)}]" if details else ""
            print(f"  {project_dir.name}{suffix}")

    if db_path.exists():
        try:
            from hydromodpy.results.catalog import SimulationCatalog

            with SimulationCatalog(workspace_root) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
            if sims.empty:
                print("# catalog: (no simulations recorded)")
            else:
                projects = (
                    sims["project"].dropna().value_counts().sort_index()
                    if "project" in sims.columns
                    else {}
                )
                print(f"# catalog: {len(sims)} run(s) across {len(projects)} project(s)")
                for project_name, count in projects.items():
                    print(f"  {project_name}  [{count} run(s)]")
        except Exception as exc:
            print(f"  Error reading hydromodpy.duckdb: {exc}", file=sys.stderr)
        return

    if not projects_dir.is_dir():
        print(
            f"No projects/ directory and no hydromodpy.duckdb found in {workspace_root}",
            file=sys.stderr,
        )
        sys.exit(EXIT_NOT_FOUND)
