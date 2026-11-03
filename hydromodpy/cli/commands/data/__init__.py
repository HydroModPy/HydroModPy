"""``hmp data`` family - the workspace data cache.

Sub-actions:

Cache management:

- ``hmp data ls``: list artefacts indexed in the workspace cache.
- ``hmp data get <request.json | variable>``: serve a data request into a folder.
- ``hmp data check``: validate ``<variable>_custom/`` folders.
- ``hmp data add <file>``: ingest a single file with explicit metadata.
- ``hmp data remove``: drop cache entries by variable/provider/station.
- ``hmp data prune --older-than N``: drop cache entries older than N days.
- ``hmp data archive --to <out>``: archive the cache + lockfile to a portable file.
- ``hmp data restore <in> [--to DIR]``: restore a cache archive into the workspace.

A run published by ``hmp publish`` is read back by ``hmp catalog import``.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.data import (
    add,
    archive,
    check,
    get,
    ls,
    prune,
    remove,
    restore,
)
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "data"
HELP: str = "Workspace data cache management"

ACTIONS = (
    ls,
    get,
    check,
    add,
    remove,
    prune,
    archive,
    restore,
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
