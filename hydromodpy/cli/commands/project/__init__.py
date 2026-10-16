"""``hmp project`` family: the projects of a workspace, and the launch of a ``[sites]`` project.

Sub-actions:

- ``hmp project new <name>``: scaffold a new project under ``projects/``.
- ``hmp project plan .``: write ``plan/<hash>/``, every site crossed with every recipe.
- ``hmp project status .``: where each case of the current plan stands.
- ``hmp project log . [--failed]``: the journal of the latest launch.
- ``hmp project case <job> N``: the case file task N of a scheduler job runs.
- ``hmp project array . --scheduler slurm``: the array job of the current plan.
- ``hmp project collect .``: write ``summary/``, tables by case and by site, figures, exports.
- ``hmp project promote <case> --trial N``: promote one trial of a session to runs/.
- ``hmp project prune <case> --keep best``: move the kept trials but the best to the trash.
- ``hmp project delete <name>``: delete a project directory.
- ``hmp project show [<name>]``: what a project holds, read from its directories.
- ``hmp project list``: list projects in the workspace.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.project import (
    array,
    case,
    collect,
    delete,
    list_cmd,
    log,
    new,
    plan,
    promote,
    prune,
    show,
    status,
)

NAME: str = "project"
HELP: str = "Manage the projects of a workspace and launch a [sites] project"

ACTIONS = (
    new,
    plan,
    status,
    log,
    case,
    array,
    collect,
    promote,
    prune,
    delete,
    show,
    list_cmd,
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
