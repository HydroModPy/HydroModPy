"""``hmp dev`` family - developer-only commands.

Sub-actions:

- ``hmp dev run-script <path>``: run a Python prototype outside ``hmp run``.
- ``hmp dev doctor``: environment diagnostics (same as top-level ``hmp doctor``).
- ``hmp dev completion [bash|zsh|fish]``: emit a shell completion script.
- ``hmp dev schema``: export the JSON Schema (autosummary entry points).
- ``hmp dev lock {update|archive|restore|verify}``: lockfile management.
- ``hmp dev config {template|check|wizard|...}``: TOML configuration tooling.
- ``hmp dev rank``: rank simulations by a metric.
- ``hmp dev manage``: local browser UI (god-module, kept as-is).
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.dev import (
    completion,
    config,
    doctor,
    lock,
    manage,
    rank,
    run_script,
    schema,
)

NAME: str = "dev"
HELP: str = "Developer-only commands (completion, schema, lock, config, manage, ...)"

ACTIONS = (run_script, doctor, completion, schema, lock, config, rank, manage)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
