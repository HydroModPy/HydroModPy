"""``hmp workspace prune`` - drop registrations whose project index is gone."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "prune"
HELP: str = "Drop registrations whose project index database is missing"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import prune_projects

    removed = prune_projects()
    if not removed:
        print("No stale projects to prune.")
        sys.exit(EXIT_OK)
    print(f"Pruned {len(removed)} stale project(s):")
    for project_id in removed:
        print(f"  - {project_id}")
    sys.exit(EXIT_OK)
