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

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.catalog import delete, gc, ls, query, show, vacuum

NAME: str = "catalog"
HELP: str = "Inspect, query, and maintain workspace catalogs"

ACTIONS = (ls, query, show, gc, vacuum, delete)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
