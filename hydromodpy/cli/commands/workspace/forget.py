"""``hmp workspace forget`` - thin wrapper around :func:`hydromodpy.forget_workspace`."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_OK

NAME: str = "forget"
HELP: str = "Unregister a workspace from the global index (files stay untouched)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("workspace_id", help="workspace_id returned by 'hmp workspace list'")
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    hmp.forget_workspace(args.workspace_id)
    print(f"Forgot workspace {args.workspace_id}.")
    sys.exit(EXIT_OK)
