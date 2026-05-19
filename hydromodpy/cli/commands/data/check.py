"""``hmp data check`` - validate drag-and-drop <variable>_custom/ folders."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_DATA_ERROR, resolve_workspace

NAME: str = "check"
HELP: str = "Validate the drag-and-drop <variable>_custom/ folders without ingesting"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("--workspace", default=None, help="Workspace root")
    parser.add_argument(
        "--variable", default=None, help="Restrict to one variable (e.g. piezometry)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to repair stale catalog entries",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.data.auto_scan import check_custom
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace = resolve_workspace(args.workspace)
    issues = check_custom(workspace, variable=args.variable)

    if getattr(args, "fix", False):
        db_path = workspace / "data" / "cache.duckdb"
        if db_path.exists():
            with DataCatalogDuckDB(db_path) as catalog:
                summary = catalog.check_and_fix()
            print(
                f"  catalog: dropped {summary['dropped']} stale entries, "
                f"refreshed {summary['refreshed']} mtimes."
            )
        else:
            print(f"  (no cache at {db_path}; skipped catalog fix)")

    if not issues:
        print(f"  OK: no schema issues in {workspace}")
        return
    print(f"  {len(issues)} issue(s) found:")
    for path, msg in issues:
        print(f"    {path}: {msg}")
    sys.exit(EXIT_DATA_ERROR)
