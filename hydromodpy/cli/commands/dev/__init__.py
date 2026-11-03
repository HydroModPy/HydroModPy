"""``hmp dev`` family - developer-only commands.

Sub-actions:

- ``hmp dev run-script <path>``: run a Python prototype outside ``hmp run``.
- ``hmp dev examples manifest``: regenerate the shipped example catalog.
- ``hmp dev manage``: local browser UI (god-module, kept as-is).
- ``hmp dev test``: run the pytest suites of this checkout.

These are out of the contract. What a user needs lives at the top level:
``hmp completion``, ``hmp lock``, ``hmp catalog rank``, ``hmp config schema``.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.dev import examples, manage, run_script, test
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "dev"
HELP: str = "Developer-only commands (run-script, examples, manage, test)"

ACTIONS = (run_script, examples, manage, test)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
