"""``hmp viz`` family - visualization helpers.

Sub-actions:

- ``hmp viz show <sim_ref> <figure>``: render one figure for one simulation.
- ``hmp viz gallery <config.toml>``: render the [display] figure gallery for
  one or several runs of the TOML.
- ``hmp viz serve``: launch the Streamlit-based configuration / inspection UI.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.viz import gallery, serve, show

NAME: str = "viz"
HELP: str = "Visualization helpers (show, gallery, streamlit UI)"

ACTIONS = (show, gallery, serve)


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
