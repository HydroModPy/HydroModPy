"""``hmp catalog ls`` - list simulations recorded in a workspace catalog."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root
from hydromodpy.core.state.paths import CATALOG_FILENAME

NAME: str = "ls"
HELP: str = "List simulations recorded in a workspace catalog"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from cwd, fallback ~/hydromodpy/)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Restrict to one project (looks at projects/<name>/catalog.duckdb)",
    )
    parser.add_argument("--solver", default=None, help="Filter by solver name (substring match)")
    parser.add_argument(
        "--catchment", default=None, help="Filter by catchment name (substring match)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of rows to print")
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()
    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    return Path(DEFAULT_ROOT).expanduser().resolve()


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog, short_id

    workspace_root = _resolve_workspace(args.workspace)
    projects_dir = workspace_root / "projects"
    if not projects_dir.is_dir():
        print(f"No projects/ directory found in {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if args.project:
        project_roots = [projects_dir / args.project]
    else:
        project_roots = sorted(
            p for p in projects_dir.iterdir() if p.is_dir() and (p / CATALOG_FILENAME).exists()
        )

    if not project_roots:
        print(f"No project catalog under {projects_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    rows_printed = 0
    for project_dir in project_roots:
        db_path = project_dir / CATALOG_FILENAME
        if not db_path.exists():
            print(f"No project catalog at {project_dir}", file=sys.stderr)
            continue
        print(f"# project: {project_dir.name}")
        try:
            with SimulationCatalog(project_dir) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
        except Exception as exc:
            print(f"  Error reading {project_dir.name}: {exc}", file=sys.stderr)
            continue
        if sims.empty:
            print(f"  (no simulations in {project_dir.name})")
            continue

        if args.solver:
            sims = sims[sims["solver"].fillna("").str.contains(args.solver, case=False)]
        if args.catchment and "catchment" in sims.columns:
            sims = sims[sims["catchment"].fillna("").str.contains(args.catchment, case=False)]

        for _, row in sims.iterrows():
            if args.limit and rows_printed >= args.limit:
                return
            sim_id = str(row["sim_id"])
            name = row.get("name", "") or "(no name)"
            solver = row.get("solver", "")
            status = row.get("status", "")
            dur = row.get("duration_s")
            dur_str = f" {dur:.1f}s" if dur else ""
            print(f"  {name}  [{short_id(sim_id)}]  solver={solver}  status={status}{dur_str}")
            rows_printed += 1
