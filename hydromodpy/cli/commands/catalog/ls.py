"""``hmp catalog ls`` - list simulations recorded in a workspace catalog.

Thin wrapper around :func:`hydromodpy.list_simulations`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, find_workspace_root

NAME: str = "ls"
HELP: str = "List simulations recorded in a workspace catalog"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp catalog ls --solver mf6 --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Restrict to one project (looks at projects/<name>/.hmp/index.duckdb)",
    )
    parser.add_argument(
        "--solver",
        default=None,
        help="Filter by solver (exact match; aliases: mf6 -> modflow6, nwt -> modflow_nwt)",
    )
    parser.add_argument(
        "--catchment", default=None, help="Filter by study area name (substring match)"
    )
    parser.add_argument(
        "--status",
        default=None,
        help="Filter by status (completed, running, failed, trashed, ...)",
    )
    parser.add_argument("--tag", default=None, help="Filter by an exact tag (e.g. pinned)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of rows to print")
    parser.set_defaults(_handler=run)
    return parser


def _resolve_workspace(workspace_arg: str | None) -> Path:
    """Resolve what to list: an explicit root, the enclosing project, or the workspace."""
    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()
    ws_override = os.environ.get("HMP_WORKSPACE")
    start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
    project_root = resolve_project_root(start)
    if (catalog_path_for(project_root)).is_file():
        return project_root
    found = find_workspace_root(start)
    if (found / "projects").is_dir() or (found / "data").is_dir():
        return found
    return Path(DEFAULT_ROOT).expanduser().resolve()


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import list_simulations
    from hydromodpy.results.catalog import iter_project_catalog_roots, short_id

    workspace_root = _resolve_workspace(args.workspace)
    if not iter_project_catalog_roots(workspace_root):
        print(f"No indexed project found under {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    df = list_simulations(
        workspace_root,
        project=args.project,
        solver=args.solver,
        catchment=args.catchment,
        status=args.status,
        tag=args.tag,
        limit=args.limit,
    )
    if df.empty:
        print(f"(no simulations recorded under {workspace_root})")
        return

    if args.format == "json":
        print(df.to_json(orient="records"))
        return
    if args.format == "csv":
        print(df.to_csv(index=False), end="")
        return

    current_project: str | None = None
    for _, row in df.iterrows():
        project = row.get("project", "")
        if project != current_project:
            print(f"# project: {project}")
            current_project = project
        sim_id = str(row["sim_id"])
        name = row.get("name", "") or "(no name)"
        solver = row.get("solver", "")
        status = row.get("status", "")
        dur = row.get("duration_s")
        dur_str = f" {dur:.1f}s" if dur else ""
        print(f"  {name}  [{short_id(sim_id)}]  solver={solver}  status={status}{dur_str}")
