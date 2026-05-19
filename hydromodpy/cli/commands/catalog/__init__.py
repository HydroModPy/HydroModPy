"""``hmp catalog`` family - inspect, query, and maintain workspace catalogs.

Sub-actions:

- ``hmp catalog ls``: list simulations (filterable by solver/catchment/project).
- ``hmp catalog query "<SQL>"``: run a raw SQL statement against the catalog.
- ``hmp catalog show <sim_ref>``: show simulation metadata (with ``--detail``).
- ``hmp catalog gc``: garbage-collect orphan caches and stale running sims.
- ``hmp catalog vacuum``: compact DuckDB and consolidate Zarr metadata.
- ``hmp catalog delete <sim_ref>``: delete a simulation row and its Zarr store.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.catalog import delete, gc, ls, query, show, vacuum

NAME: str = "catalog"
HELP: str = "Inspect, query, and maintain workspace catalogs"

ACTIONS = (ls, query, show, gc, vacuum, delete)


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


__all__ = ("NAME", "HELP", "ACTIONS", "register")
