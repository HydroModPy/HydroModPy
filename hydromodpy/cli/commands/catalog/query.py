"""``hmp catalog query`` - run a SQL statement against the workspace DuckDB.

Thin wrapper around :func:`hydromodpy.query_catalog`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND, find_catalog_root

NAME: str = "query"
HELP: str = "Run a SQL statement against the workspace catalog.duckdb"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("sql", help="SQL statement to execute against the catalog")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Project catalog root (default: auto-detect from cwd)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a formatted table",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Wrap the SQL in a LIMIT clause to cap the result set",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    try:
        df = hmp.query_catalog(args.sql, workspace=workspace_root, limit=args.limit)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except duckdb.Error as exc:
        print(f"SQL error: {exc}", file=sys.stderr)
        sys.exit(EXIT_GENERIC)

    if df is None or df.empty:
        print("(empty result)")
        return

    if args.json:
        print(df.to_json(orient="records", date_format="iso", indent=2))
        return

    print(df.to_string(index=False))
