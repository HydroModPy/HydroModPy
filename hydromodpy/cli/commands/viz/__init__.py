"""``hmp viz`` family - visualization helpers.

Sub-actions:

- ``hmp viz list``: print the figure names accepted by ``[display].figures``.
- ``hmp viz show <sim_ref> <figure>``: render one figure for one simulation.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.viz import list_cmd, show
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "viz"
HELP: str = "List the figures and draw one"

ACTIONS = (list_cmd, show)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
