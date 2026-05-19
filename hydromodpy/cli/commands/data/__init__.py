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
    sub = parser.add_subparsers(dest="action", metavar="<action>")
    for action in ACTIONS:
        action.register(sub)
    parser.set_defaults(_handler=lambda args: _print_help_when_missing(parser, args))
    return parser


def _print_help_when_missing(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not getattr(args, "action", None):
        parser.print_help()


# Backwards-compatible export used by tests (``from hydromodpy.cli.commands.data
# import _parse_bbox``). Keep it pointing to the canonical implementation.
_parse_bbox = get._parse_bbox


__all__ = ("NAME", "HELP", "ACTIONS", "register", "_parse_bbox")
