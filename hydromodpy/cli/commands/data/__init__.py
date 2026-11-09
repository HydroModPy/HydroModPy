"""``hmp data`` family - the data cache of a workspace.

The cache is the sidecar ``<file>.json`` next to each fetched file. A file the
user keeps under ``inputs/`` is read in place and is no row of the cache.

Sub-actions:

- ``hmp data ls``: list the rows of the cache.
- ``hmp data get <request.json | variable>``: serve a data request into a folder.
- ``hmp data remove``: drop rows by variable, provider or station.
- ``hmp data prune --older-than N``: drop rows older than N days, except the files a
  run or a lockfile cites.
- ``hmp data lock``: write ``hydromodpy.lock``, the digest of each file a project read.
  ``hmp data lock --check [--strict]`` compares the files on disk with it.
- ``hmp data archive --to <out>``: archive the cache and its lockfile to a portable file.
- ``hmp data restore <in> [--to DIR]``: restore a cache archive into the workspace.

A run published by ``hmp publish`` is read back by ``hmp catalog import``.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.data import (
    archive,
    get,
    lock,
    ls,
    prune,
    remove,
    restore,
)
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "data"
HELP: str = "Data cache of a workspace and the lockfile of a project"

ACTIONS = (
    ls,
    get,
    remove,
    prune,
    lock,
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
