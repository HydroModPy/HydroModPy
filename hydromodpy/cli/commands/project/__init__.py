"""``hmp project`` family - project lifecycle commands.

Sub-actions:

- ``hmp project new <name>``: scaffold a new project under ``projects/``.
- ``hmp project list``: list projects in the workspace.
- ``hmp project show <name>``: print a project summary (catalog stats).
- ``hmp project delete <name>``: delete a project and its catalog data.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.project import delete, list_cmd, new, show

NAME: str = "project"
HELP: str = "Manage projects within a workspace"

ACTIONS = (new, list_cmd, show, delete)


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
