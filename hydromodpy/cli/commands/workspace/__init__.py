"""``hmp workspace`` family - scaffold, list and clean a workspace.

There is no machine-wide registry: a workspace is what its tree holds, and
``list`` walks it.

Sub-actions:

- ``hmp workspace init [<path>]``: scaffold a HydroModPy workspace.
- ``hmp workspace list [<path>]``: list the sealed runs of every project under
  a workspace, read from their directories.
- ``hmp workspace clean [--dry-run]``: remove generated workspace artefacts.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.workspace import clean, init_cmd, list_cmd

NAME: str = "workspace"
HELP: str = "Scaffold, list and clean a workspace"

ACTIONS = (init_cmd, list_cmd, clean)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
