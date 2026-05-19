"""``hmp dev`` family - developer-only commands.

Sub-actions:

- ``hmp dev run-script <path>``: run a Python prototype outside ``hmp run``.
- ``hmp dev completion [bash|zsh|fish]``: emit a shell completion script.
- ``hmp dev schema``: export the JSON Schema (autosummary entry points).
- ``hmp dev lock {update|archive|restore|verify}``: lockfile management.
- ``hmp dev config {template|check|wizard|...}``: TOML configuration tooling.
- ``hmp dev rank``: rank simulations by a metric.
- ``hmp dev manage``: local browser UI (god-module, kept as-is).
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.dev import (
    completion,
    config,
    lock,
    manage,
    rank,
    run_script,
    schema,
)

NAME: str = "dev"
HELP: str = "Developer-only commands (completion, schema, lock, config, manage, ...)"

ACTIONS = (run_script, completion, schema, lock, config, rank, manage)


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
