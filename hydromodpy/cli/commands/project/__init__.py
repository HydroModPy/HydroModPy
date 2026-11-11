"""``hmp project`` family: the projects of a workspace, and the plan of a ``[sites]`` project.

``hmp show .`` says what a project holds, and ``hmp ls --plan`` where its plan stands.

Sub-actions:

- ``hmp project new <name>``: scaffold a new project under ``projects/``.
- ``hmp project plan .``: write ``plan/<hash>/``, every site crossed with every recipe.
- ``hmp project log . [--failed]``: the journal of the latest launch.
- ``hmp project delete <name>``: delete a project directory.
- ``hmp project list``: list projects in the workspace.
- ``hmp project import X.tar -w <workspace>``: install a package ``hmp publish --package`` wrote.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.project import (
    delete,
    import_package,
    list_cmd,
    log,
    new,
    plan,
)
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "project"
HELP: str = "Manage the projects of a workspace and plan a [sites] project"

ACTIONS = (new, plan, log, delete, list_cmd, import_package)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
