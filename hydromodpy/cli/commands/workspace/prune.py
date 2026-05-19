"""``hmp workspace prune`` - drop registrations whose catalog.duckdb is missing."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "prune"
HELP: str = "Drop registrations whose catalog.duckdb is missing"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        removed = gi.prune()
    if not removed:
        print("No stale workspaces to prune.")
        sys.exit(EXIT_OK)
    print(f"Pruned {len(removed)} stale workspace(s):")
    for wid in removed:
        print(f"  - {wid}")
    sys.exit(EXIT_OK)
