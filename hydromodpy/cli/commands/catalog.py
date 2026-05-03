"""``hmp catalog`` - query the hidden inter-project catalog index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG

NAME: str = "catalog"
HELP: str = "Query the global inter-project catalog"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    commands = parser.add_subparsers(dest="catalog_command", required=True)

    projects = commands.add_parser("projects", help="List registered projects")
    projects.set_defaults(_handler=run)

    reindex = commands.add_parser("reindex", help="Register project catalogs from a workspace")
    reindex.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Workspace root to scan (default: cwd workspace)",
    )
    reindex.set_defaults(_handler=run)

    query = commands.add_parser("query", help="Run SQL against all_* federated views")
    query.add_argument("sql", help="SQL query to execute")
    query.add_argument(
        "--workspace",
        default=None,
        help="Optional workspace root to scan before querying",
    )
    query.set_defaults(_handler=run)

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    command = getattr(args, "catalog_command", None)
    if command == "projects":
        _cmd_projects()
        return
    if command == "reindex":
        _cmd_reindex(args)
        return
    if command == "query":
        _cmd_query(args)
        return
    print("Usage: hmp catalog {projects,reindex,query} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _cmd_projects() -> None:
    from hydromodpy.results.catalog import CatalogIndex

    with CatalogIndex() as index:
        df = index.projects()
    if df.empty:
        print("No projects registered.")
        return
    print(df.to_string(index=False))


def _cmd_reindex(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.results.catalog import CatalogIndex

    start = Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    workspace = find_workspace_root(start)
    with CatalogIndex() as index:
        count = index.register_workspace(workspace)
    print(f"Registered {count} project catalog(s) from {workspace}")


def _cmd_query(args: argparse.Namespace) -> None:
    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.results.catalog import CatalogIndex

    with CatalogIndex() as index:
        workspace_arg = getattr(args, "workspace", None)
        if workspace_arg:
            workspace = find_workspace_root(Path(workspace_arg).expanduser().resolve())
            index.register_workspace(workspace)
        df = index.query(args.sql)
    print(df.to_string(index=False))
