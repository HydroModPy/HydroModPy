"""``hmp workspace search`` - full-text search across registered workspaces."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "search"
HELP: str = "Full-text search across all workspaces registered in the global index"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("term", help="Free-form search term")
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of rows to print (default: 20)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex(read_only=True) as gi:
        df = gi.search(args.term)
    if df is None or df.empty:
        print(f"No matches for {args.term!r}.")
        sys.exit(EXIT_OK)

    df = df.head(args.limit)
    columns = [
        c for c in ("workspace_id", "sim_id", "name", "project", "description") if c in df.columns
    ]
    if not columns:
        columns = list(df.columns)
    print(df[columns].to_string(index=False))
    sys.exit(EXIT_OK)
