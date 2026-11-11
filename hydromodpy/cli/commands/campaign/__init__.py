"""``hmp campaign`` family: run a project of many cases, and keep what a calibration found.

Sub-actions:

- ``hmp campaign array . --scheduler slurm``: the array job of the current plan.
- ``hmp campaign case <job> N``: the case file task N of a scheduler job runs.
- ``hmp campaign collect .``: write ``summary/``, tables by case and by site, figures, exports.
- ``hmp campaign promote <case> --trial N``: promote one trial of a session to runs/.
- ``hmp campaign prune <case> --keep best``: move the kept trials but the best to the trash.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.campaign import array, case, collect, promote, prune
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "campaign"
HELP: str = "Run a project of many cases, collect it, keep what a calibration found"

ACTIONS = (array, case, collect, promote, prune)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = (
    "NAME",
    "HELP",
    "ACTIONS",
    "register",
)
