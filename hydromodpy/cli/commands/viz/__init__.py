"""``hmp viz`` family - visualization helpers.

Sub-actions:

- ``hmp viz show <sim_ref> <figure>``: render one figure for one simulation.
- ``hmp viz gallery <config.toml>``: render the [display] figure gallery for
  one or several runs of the TOML.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.viz import gallery, show

NAME: str = "viz"
HELP: str = "Visualization helpers (show, gallery)"

ACTIONS = (show, gallery)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
