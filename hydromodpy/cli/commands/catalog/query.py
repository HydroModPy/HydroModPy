"""``hmp catalog query`` - run a SQL statement against the workspace DuckDB catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND, find_catalog_root
from hydromodpy.core.state.paths import CATALOG_FILENAME

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
    import duckdb

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    sql = args.sql.strip()
    if args.limit is not None:
        sql = f"SELECT * FROM ({sql}) LIMIT {int(args.limit)}"

    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
        try:
            df = conn.execute(sql).fetchdf()
        finally:
            conn.close()
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
