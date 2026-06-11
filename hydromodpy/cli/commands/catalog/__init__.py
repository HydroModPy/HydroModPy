"""``hmp catalog`` family - inspect, query, and maintain workspace catalogs.

Sub-actions:

- ``hmp catalog ls``: list simulations (filterable by solver/catchment/project).
- ``hmp catalog query "<SQL>"``: run a raw SQL statement against the catalog.
- ``hmp catalog show <sim_ref>``: show simulation metadata (with ``--detail``).
- ``hmp catalog gc``: garbage-collect orphan caches and stale running sims.
- ``hmp catalog vacuum``: compact DuckDB and consolidate Zarr metadata.
- ``hmp catalog delete <sim_ref>``: move a run to the trash (``--now`` to purge).
- ``hmp catalog restore <sim_ref>``: bring a trashed run back.
- ``hmp catalog trash [--empty]``: list trashed runs or empty the trash.
- ``hmp catalog tag <sim_ref> TAG... [--rm TAG]``: add/remove tags.
- ``hmp catalog note <sim_ref> "<text>"``: append a timestamped note.
- ``hmp catalog rename <sim_ref> <new_name>``: rename a run (storage never moves).
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.catalog import (
    delete,
    gc,
    ls,
    note,
    query,
    rename,
    restore,
    show,
    tag,
    trash,
    vacuum,
)

NAME: str = "catalog"
HELP: str = "Inspect, query, and maintain workspace catalogs"

ACTIONS = (ls, query, show, gc, vacuum, delete, restore, trash, tag, note, rename)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
