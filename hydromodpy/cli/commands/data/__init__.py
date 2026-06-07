"""``hmp data`` family - workspace data cache and package exchange.

Sub-actions:

Cache management:

- ``hmp data ls``: list artefacts indexed in the workspace cache.
- ``hmp data get <variable>``: fetch an upstream variable.
- ``hmp data check``: validate ``<variable>_custom/`` folders.
- ``hmp data add <file>``: ingest a single file with explicit metadata.
- ``hmp data remove``: drop cache entries by variable/provider/station.
- ``hmp data prune --older-than N``: drop cache entries older than N days.
- ``hmp data archive <out>``: archive the cache + lockfile to a portable file.
- ``hmp data restore <in>``: restore a cache archive into the workspace.

Package exchange:

- ``hmp data export <project>``: export geographic data or simulation results.
- ``hmp data export-package <sim_ref>``: bundle a simulation as a portable
  ``.hmp`` archive (tar.zst with RO-Crate manifest).
- ``hmp data import <package>``: import a ``.hmp`` archive and dematerialise
  its bundled inputs into a project catalog.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.data import (
    add,
    archive,
    check,
    export,
    export_package,
    get,
    import_cmd,
    ls,
    prune,
    remove,
    restore,
)

NAME: str = "data"
HELP: str = "Workspace data cache management and .hmp package exchange"

ACTIONS = (
    ls,
    get,
    check,
    add,
    remove,
    prune,
    archive,
    restore,
    export,
    export_package,
    import_cmd,
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
