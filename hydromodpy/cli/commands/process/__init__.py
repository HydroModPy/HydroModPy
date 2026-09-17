"""``hmp process`` family - drive a capability as an external process.

A capability is a function from a validated input document to a directory of
sealed artefacts. The caller creates the directory, writes ``request.json``
into it, and hands over the path; this family is how that path is handed over
from a shell.

Sub-actions:

- ``hmp process list``: the capabilities this build serves.
- ``hmp process describe <id>``: the machine-readable description of one,
  byte-identical to the document that ships in the wheel.
- ``hmp process run <id> --job DIR``: run one. stdout carries exactly one JSON
  document, byte-identical to ``DIR/outcome.json``; everything human goes to
  stderr; the exit code is the typed one of the outcome.
- ``hmp process verify --job DIR``: re-check a finished directory against its
  own seal, reading only the disk.

Two of the four write bytes a machine reads and never a rendering of them. The
description is generated from the declaration and the Pydantic model by
``python -m tools.processes``, never written by hand, and a gate refuses a
committed document the generator no longer reproduces.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.process import describe, list_capabilities, run_job, verify_job

NAME: str = "process"
HELP: str = "Run a capability as an external process, in one job directory"

ACTIONS = (list_capabilities, describe, run_job, verify_job)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
