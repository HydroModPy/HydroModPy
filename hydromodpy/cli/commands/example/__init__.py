"""``hmp example`` family - drop one shipped example into a workspace.

Sub-actions:

- ``hmp example list``: the catalogue, offline, with what this machine misses.
- ``hmp example show <id>``: one example file by file, cached or missing.
- ``hmp example add <id>``: fetch what is missing and write it into a workspace.

The catalogue is read from ``hydromodpy/examples/catalog.toml`` inside the
wheel, so ``list`` needs no network and cannot promise what the installed
version does not know about.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.example import add, show
from hydromodpy.cli.commands.example import list_cmd as list_action

NAME: str = "example"
HELP: str = "List the shipped examples and install one into a workspace"

ACTIONS = (list_action, show, add)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
