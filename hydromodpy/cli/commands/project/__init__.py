"""``hmp project`` family - project lifecycle commands.

Sub-actions:

- ``hmp project new <name>``: scaffold a new project under ``projects/``.
- ``hmp project list``: list projects in the workspace.
- ``hmp project show <name>``: print a project summary (catalog stats).
- ``hmp project delete <name>``: delete a project and its catalog data.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.project import delete, list_cmd, new, show

NAME: str = "project"
HELP: str = "Manage projects within a workspace"

ACTIONS = (new, list_cmd, show, delete)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
