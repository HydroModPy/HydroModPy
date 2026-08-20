"""``hmp workspace`` family - workspace lifecycle and global-index commands.

The global index registers PROJECTS, one row per project root, because a
project root is what owns an index database. The workspace-scoped actions
(``init``, ``clean``) act on a workspace; the index-scoped ones act on the
projects it contains.

Sub-actions:

- ``hmp workspace init [<path>]``: scaffold a HydroModPy workspace.
- ``hmp workspace list``: list the projects registered in the global index.
- ``hmp workspace register <root_uri>``: register a project, or every project
  held by a workspace root.
- ``hmp workspace search <term>``: full-text search across registered projects.
- ``hmp workspace forget <project_id>``: drop one project registration.
- ``hmp workspace prune``: drop registrations whose project index is missing.
- ``hmp workspace clean [--dry-run]``: remove generated workspace artefacts.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.workspace import (
    clean,
    forget,
    init_cmd,
    list_cmd,
    prune,
    search,
)
from hydromodpy.cli.commands.workspace import (
    register as register_cmd,
)

NAME: str = "workspace"
HELP: str = "Workspace lifecycle, project registration in the global index, and maintenance"

ACTIONS = (init_cmd, list_cmd, register_cmd, search, forget, prune, clean)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
