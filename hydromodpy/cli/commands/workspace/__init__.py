"""``hmp workspace`` family - workspace lifecycle and maintenance commands.

Sub-actions:

- ``hmp workspace init [<path>]``: scaffold a HydroModPy workspace.
- ``hmp workspace list``: list workspaces registered in the global index.
- ``hmp workspace clean [--dry-run]``: remove generated workspace artefacts.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.workspace import clean, init_cmd, list_cmd

NAME: str = "workspace"
HELP: str = "Workspace lifecycle and maintenance commands"

ACTIONS = (init_cmd, list_cmd, clean)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="action", metavar="<action>")
    for action in ACTIONS:
        action.register(sub)
    parser.set_defaults(_handler=lambda args: _print_help_when_missing(parser, args))
    return parser


def _print_help_when_missing(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not getattr(args, "action", None):
        parser.print_help()


__all__ = ("NAME", "HELP", "ACTIONS", "register")
