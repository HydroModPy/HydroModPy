"""``hmp lock`` family: the lockfile that pins the data a project read.

``hydromodpy.lock`` belongs to a project root, while the data cache it pins
belongs to a workspace. So both verbs take both: ``--project`` names the
lockfile, ``-w`` names the cache. Omitting ``--project`` resolves the project
the current directory sits in, unless ``--to`` or ``--lockfile`` names the file
outright: such a path is the address already, and the directory it sits in is
the project it describes. Omitting ``-w`` resolves the workspace that holds that
project.

Sub-actions:

- ``hmp lock update``: scan the cache and write ``hydromodpy.lock``.
- ``hmp lock verify``: verify the cache matches the lockfile.

An archive of the cache and its lockfile is ``hmp data archive``.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.lock import update, verify
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "lock"
HELP: str = "Write or verify the lockfile that pins the data of a project (hydromodpy.lock)"

ACTIONS = (update, verify)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
