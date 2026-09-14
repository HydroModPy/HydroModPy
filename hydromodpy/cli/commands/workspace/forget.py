"""``hmp workspace forget`` - drop one project registration from the global index."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "forget"
HELP: str = "Unregister a project from the global index (files stay untouched)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project_id", help="project_id returned by 'hmp workspace list'")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.workspace import forget_project

    forget_project(args.project_id)
    print(f"Forgot project {args.project_id}.")
    sys.exit(EXIT_OK)
