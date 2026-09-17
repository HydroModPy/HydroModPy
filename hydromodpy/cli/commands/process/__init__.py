"""``hmp process`` family - drive a capability as an external process.

A capability is a function from a validated input document to a directory of
sealed artefacts. The caller creates the directory, writes ``request.json``
into it, and hands over the path; this family is how that path is handed over
from a shell.

Sub-actions:

- ``hmp process list``: the capabilities this build serves.
- ``hmp process run <id> --job DIR``: run one. stdout carries exactly one JSON
  document, byte-identical to ``DIR/outcome.json``; everything human goes to
  stderr; the exit code is the typed one of the outcome.
- ``hmp process verify --job DIR``: re-check a finished directory against its
  own seal, reading only the disk.

The verb that prints a machine-readable process description is not here yet:
it is generated from the declaration and the Pydantic model, never written by
hand, and it arrives with the generator that writes it.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.process import list_capabilities, run_job, verify_job

NAME: str = "process"
HELP: str = "Run a capability as an external process, in one job directory"

ACTIONS = (list_capabilities, run_job, verify_job)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
