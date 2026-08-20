"""``hmp catalog query`` - run a SQL statement against the workspace DuckDB.

Thin wrapper around :func:`hydromodpy.query_catalog`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from hydromodpy.cli._conventions import format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND
from hydromodpy.core.state.paths import resolve_project_root

NAME: str = "query"
HELP: str = "Run a SQL statement against the project index database"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog='Example:\n  hmp catalog query "SELECT name, solver FROM simulations" --format json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sql", help="SQL statement to execute against the catalog")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Wrap the SQL in a LIMIT clause to cap the result set",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import query_catalog

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        df = query_catalog(args.sql, workspace=workspace_root, limit=args.limit)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except duckdb.Error as exc:
        print(f"SQL error: {exc}", file=sys.stderr)
        sys.exit(EXIT_GENERIC)

    if df is None or df.empty:
        print("(empty result)")
        return

    if args.format == "json":
        print(df.to_json(orient="records", date_format="iso", indent=2))
        return
    if args.format == "csv":
        print(df.to_csv(index=False), end="")
        return

    print(df.to_string(index=False))
