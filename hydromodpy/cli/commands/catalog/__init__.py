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
- ``hmp catalog diff <ref_a> <ref_b>``: compare two runs' params and outlet metrics.
- ``hmp catalog watch``: show running runs with heartbeat staleness.
- ``hmp catalog export <sim_ref> [-o FILE]``: write a portable ``.hmp`` archive.
- ``hmp catalog import <FILE.hmp>``: restore a run from an archive.
- ``hmp catalog rerun <sim_ref> [--set path=value]``: re-launch from the snapshot.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.catalog import (
    delete,
    diff,
    export,
    gc,
    import_archive,
    ls,
    note,
    query,
    rename,
    rerun,
    restore,
    show,
    tag,
    trash,
    vacuum,
    watch,
)

NAME: str = "catalog"
HELP: str = "Inspect, query, and maintain workspace catalogs"

ACTIONS = (
    ls,
    query,
    show,
    gc,
    vacuum,
    delete,
    restore,
    trash,
    tag,
    note,
    rename,
    diff,
    watch,
    export,
    import_archive,
    rerun,
)


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = add_action_subparsers(parser)
    for action in ACTIONS:
        action.register(sub)
    return parser


__all__ = ("NAME", "HELP", "ACTIONS", "register")
