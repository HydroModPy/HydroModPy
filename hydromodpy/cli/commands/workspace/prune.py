"""``hmp workspace prune`` - thin wrapper around :func:`hydromodpy.prune_workspaces`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "prune"
HELP: str = "Drop registrations whose index database is missing"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import prune_workspaces

    removed = prune_workspaces()
    if not removed:
        print("No stale workspaces to prune.")
        sys.exit(EXIT_OK)
    print(f"Pruned {len(removed)} stale workspace(s):")
    for wid in removed:
        print(f"  - {wid}")
    sys.exit(EXIT_OK)
