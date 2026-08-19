"""``hmp workspace search`` - full-text search across the registered projects."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "search"
HELP: str = "Full-text search across every project registered in the global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("term", help="Free-form search term")
    parser.add_argument("--limit", type=int, default=20, help="Maximum rows to print")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import search_projects

    df = search_projects(args.term, limit=args.limit)
    if df is None or df.empty:
        print(f"No matches for {args.term!r}.")
        sys.exit(EXIT_OK)

    columns = [
        c for c in ("project_id", "sim_id", "name", "project", "description") if c in df.columns
    ]
    if not columns:
        columns = list(df.columns)
    print(df[columns].to_string(index=False))
    sys.exit(EXIT_OK)
