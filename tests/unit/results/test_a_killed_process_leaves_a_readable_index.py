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

The kill here is real: ``Popen.kill`` on a child process, ``SIGKILL`` on POSIX
and ``TerminateProcess`` on Windows, no handler, no ``finally``, no flush.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.paths import catalog_path_for

_WRITTEN = "rows written"

_KILLED_BOOTSTRAP = f"""
import sys
from pathlib import Path

from hydromodpy.results.catalog import Catalog

catalog = Catalog(Path(sys.argv[1]))
catalog.connection.execute(
    "INSERT INTO workflow_events (run_id, step_name, event_type) VALUES ('r', 'build_mesh', 'log')"
)
print({_WRITTEN!r}, flush=True)
sys.stdin.read()
"""

# Popen.kill sends SIGKILL on POSIX and calls TerminateProcess(handle, 1) on Windows.
_KILLED_EXIT = 1 if sys.platform == "win32" else -signal.SIGKILL


@pytest.fixture(scope="module")
def killed_while_bootstrapping(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a project index in a child, then kill that child outright."""
    root = tmp_path_factory.mktemp("killed_bootstrap")
    child = subprocess.Popen(
        [sys.executable, "-c", _KILLED_BOOTSTRAP, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    watchdog = threading.Timer(300, child.kill)
    watchdog.start()
    output: list[str] = []
    try:
        for line in child.stdout:
            output.append(line)
            if line.strip() == _WRITTEN:
                child.kill()
                break
        returncode = child.wait()
    finally:
        watchdog.cancel()
        child.stdin.close()
        child.stdout.close()

    assert output and output[-1].strip() == _WRITTEN, (
        f"the child stopped before writing its rows (exit {returncode}): {''.join(output)[-2000:]}"
    )
    assert returncode == _KILLED_EXIT, (
        f"the child was not killed outright (exit {returncode}): {''.join(output)[-2000:]}"
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
