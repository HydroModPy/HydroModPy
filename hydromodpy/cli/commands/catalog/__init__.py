"""``hmp catalog`` family - read the index of a project and maintain its tree.

Sub-actions:

- ``hmp catalog ls``: list the runs (filterable by solver, site, status, label, tag).
- ``hmp catalog query "<SQL>"``: run one read-only SQL statement against the index.
- ``hmp catalog show <sim_ref>``: print the README of one run, or its facts
  from the index (``--detail``, ``--format json``).
- ``hmp catalog point <sim_ref>... --var V``: read a variable in one cell,
  named by coordinates, cell id or depth, on one or several runs.
- ``hmp catalog gc``: plans by default; ``--apply`` marks dead attempts
  aborted, trashes old versions and removes expired trash, each removed
  directory leaving a tombstone.
- ``hmp catalog reindex``: rebuild the index from the run directories.
- ``hmp catalog delete <ref>``: move a run or a session to ``trash/``
  (``--now`` removes it, leaving a tombstone).
- ``hmp catalog restore <ref>``: bring a trashed directory back.
- ``hmp catalog trash [--empty]``: list the trash or empty it.
- ``hmp catalog tag <sim_ref> TAG... [--rm TAG]``: add or remove tags
  (``runs/<run>/annotations.json``).
- ``hmp catalog note <sim_ref> "<text>"``: append a timestamped note.
- ``hmp catalog rename <sim_ref> <new_name>``: rename a run (its directory moves).
- ``hmp catalog diff <ref_a> <ref_b>``: compare the parameters and metrics of two runs.
- ``hmp catalog watch``: show the running attempts with the age of their pulse.
- ``hmp catalog import <DIR|TAR>``: import a run written by ``hmp publish``.
- ``hmp catalog rerun <sim_ref> [--set path=value]``: re-launch from the frozen config.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli._conventions import add_action_subparsers
from hydromodpy.cli.commands.catalog import (
    delete,
    diff,
    gc,
    import_archive,
    ls,
    note,
    point,
    query,
    reindex,
    rename,
    rerun,
    restore,
    show,
    tag,
    trash,
    watch,
)

NAME: str = "catalog"
HELP: str = "Read the index of a project and maintain its runs"

ACTIONS = (
    ls,
    query,
    show,
    point,
    gc,
    reindex,
    delete,
    restore,
    trash,
    tag,
    note,
    rename,
    diff,
    watch,
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
