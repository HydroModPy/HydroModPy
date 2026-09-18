"""A project index survives the death of the process that created it.

DuckDB commits into ``<db>.wal`` and only folds it into the database file at a
clean close. A process killed by an uncatchable signal leaves the journal
behind, and until the migration runner checkpointed its own DDL, that journal
carried the ``ALTER TABLE`` of migration 0003. Replaying it raises
``INTERNAL Error: ... Calling DatabaseManager::GetDefaultDatabase with no
default database set`` - inside ``duckdb.connect``, so the database could not be
opened again by anything, read-only included.

What that cost: the whole first session of a project. Every row of the workflow
journal a ``--resume`` reads lives in that index, so a run killed at any point
before its first clean close was not resumable, it was gone.

The kill here is real: ``SIGKILL`` to a child process, no handler, no
``finally``, no flush.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.paths import catalog_path_for

_KILLED_BOOTSTRAP = """
import os
import signal
import sys
from pathlib import Path

from hydromodpy.results.catalog import Catalog

catalog = Catalog(Path(sys.argv[1]))
catalog.connection.execute(
    "INSERT INTO workflow_events (run_id, step_name, event_type) VALUES ('r', 'build_mesh', 'log')"
)
os.kill(os.getpid(), signal.SIGKILL)
"""


@pytest.fixture(scope="module")
def killed_while_bootstrapping(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a project index in a child, then kill that child with SIGKILL."""
    root = tmp_path_factory.mktemp("killed_bootstrap")
    completed = subprocess.run(
        [sys.executable, "-c", _KILLED_BOOTSTRAP, str(root)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == -9, (
        f"the child was not killed by SIGKILL (exit {completed.returncode}): "
        f"{completed.stderr[-2000:]}"
    )
    return root


def test_the_index_of_a_killed_process_can_be_opened_again(
    killed_while_bootstrapping: Path,
) -> None:
    """A plain DuckDB open, with nothing of HydroModPy to repair it first."""
    index = catalog_path_for(killed_while_bootstrapping)

    connection = duckdb.connect(str(index))
    try:
        tables = connection.execute(
            "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'workflow_events'"
        ).fetchone()
    finally:
        connection.close()

    assert tables == (1,)


def test_the_rows_written_before_the_kill_are_still_there(
    killed_while_bootstrapping: Path,
) -> None:
    """The journal is replayed, not dropped: a checkpoint is not a truncation."""
    connection = duckdb.connect(str(catalog_path_for(killed_while_bootstrapping)))
    try:
        events = connection.execute("SELECT COUNT(*) FROM workflow_events").fetchone()
    finally:
        connection.close()

    assert events == (1,)
