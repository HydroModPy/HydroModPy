"""``hmp list`` — list projects or runs in a workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy._cli.helpers import EXIT_NOT_FOUND, find_workspace_root


NAME = "list"
HELP = "List projects or runs in a workspace"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "project", nargs="?",
        help="Project name to list runs for (omit for project listing)",
    )
    parser.add_argument(
        "--workspace", default=None,
        help="Workspace root (default: ~/hydromodpy/)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    workspace_root = Path(args.workspace or DEFAULT_ROOT).expanduser().resolve()
    projects_dir = workspace_root / "projects"

    if not projects_dir.is_dir():
        print(f"No projects/ directory found in {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.project:
        project_dir = projects_dir / args.project
        if not project_dir.is_dir():
            print(f"Project not found: {args.project}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        workspace_root = find_workspace_root(project_dir)
        db_path = workspace_root / "hydromodpy.duckdb"
        if not db_path.exists():
            print(f"No hydromodpy.duckdb in {workspace_root}")
            return
        try:
            from hydromodpy.results.catalog import (
                SimulationCatalog,
                short_id,
            )
            catalog = SimulationCatalog(workspace_root)
            sims = catalog.list_simulations(project=args.project)
            if sims.empty:
                print(f"  No simulations recorded in {args.project}")
            else:
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
            catalog.close()
        except Exception as exc:
            print(f"  Error reading hydromodpy.duckdb: {exc}", file=sys.stderr)
        return

    for project_dir in sorted(projects_dir.iterdir()):
        if project_dir.is_dir():
            has_project_toml = (project_dir / "project.toml").exists()
            run_tomls = list(project_dir.glob("run_*.toml"))
            details = []
            if has_project_toml:
                details.append("project.toml")
            if run_tomls:
                details.append(f"{len(run_tomls)} run(s)")
            suffix = f"  [{', '.join(details)}]" if details else ""
            print(f"  {project_dir.name}{suffix}")
