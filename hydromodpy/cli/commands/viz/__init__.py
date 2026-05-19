"""``hmp viz`` family - visualization helpers.

Sub-actions:

- ``hmp viz serve``: launch the Streamlit-based configuration / inspection UI.

``hmp display`` (single-figure render) and ``hmp report`` (HTML report)
still live at the top level. They will be folded into this family in a
subsequent iteration of the interface refactor.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.viz import serve

NAME: str = "viz"
HELP: str = "Visualization helpers (streamlit UI, future show/gallery)"

ACTIONS = (serve,)


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
