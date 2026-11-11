"""``hmp catalog`` family - maintain the index of a project and its tree.

Reading is ``hmp ls``, ``hmp show`` and ``hmp diff``. This family keeps what they read.

Sub-actions:

- ``hmp catalog query "<SQL>"``: run one read-only SQL statement against the index.
- ``hmp catalog gc``: says what it would do; ``-y`` marks dead attempts
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
- ``hmp catalog watch``: show the running attempts with the age of their pulse.
- ``hmp catalog import <DIR|TAR>``: import a run written by ``hmp publish``.
- ``hmp catalog rerun <sim_ref> [--set path=value]``: re-launch from the frozen config.
"""

from __future__ import annotations

import argparse

from hydromodpy.cli.commands.catalog import (
    delete,
    gc,
    import_archive,
    note,
    query,
    reindex,
    rename,
    rerun,
    restore,
    tag,
    trash,
    watch,
)
from hydromodpy.cli.conventions import add_action_subparsers

NAME: str = "catalog"
HELP: str = "Maintain the index of a project and its runs"

ACTIONS = (
    query,
    gc,
    reindex,
    delete,
    restore,
    trash,
    tag,
    note,
    rename,
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


__all__ = (
    "NAME",
    "HELP",
    "ACTIONS",
    "register",
)
