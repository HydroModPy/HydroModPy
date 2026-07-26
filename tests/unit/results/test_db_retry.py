from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

import hydromodpy.core.io.db_retry as db_retry
from hydromodpy.core.logging import get_logger


def test_connect_with_retry_retries_lock_contention_until_success(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []
    sentinel = object()

    def fake_connect(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 4:
            raise duckdb.IOException("IO Error: conflicting lock is held by another process")
        return sentinel

    monkeypatch.setattr(db_retry.duckdb, "connect", fake_connect)
    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda a, b: 0.0)

    conn = db_retry.connect_with_retry(
        "workspace.duckdb",
        retries=4,
        backoff=0.1,
        max_backoff=1.0,
    )

    assert conn is sentinel
    assert calls["count"] == 4
    assert sleeps == [0.1, 0.2, 0.4]


def test_connect_with_retry_does_not_retry_non_lock_io_errors(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_connect(*args, **kwargs):
        calls["count"] += 1
        raise duckdb.IOException("IO Error: Cannot open file 'missing.duckdb': No such file")

    monkeypatch.setattr(db_retry.duckdb, "connect", fake_connect)
    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)

    with pytest.raises(duckdb.IOException, match="No such file"):
        db_retry.connect_with_retry(
            "missing.duckdb",
            retries=4,
            backoff=0.1,
            max_backoff=1.0,
        )

    assert calls["count"] == 1
    assert sleeps == []


def test_with_lock_retry_retries_lock_contention_until_success(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda a, b: 0.0)

    @db_retry.with_lock_retry(retries=3, backoff=0.1, max_backoff=1.0)
    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise duckdb.IOException("IO Error: file is used by another process")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3
    assert sleeps == [0.1, 0.2]


# ---------------------------------------------------------------------------
# Write-ahead log left behind by an unclean shutdown
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_hmp_logs() -> Iterator[list[logging.LogRecord]]:
    """Capture records on the ``hydromodpy`` logger (propagation is disabled)."""
    parent = get_logger("hydromodpy")
    previous_level = parent.level
    parent.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.DEBUG)
    parent.addHandler(handler)
    try:
        yield records
    finally:
        parent.removeHandler(handler)
        parent.setLevel(previous_level)


def _database_killed_mid_write(tmp_path: Path) -> Path:
    """Return a database in the exact state an uncatchable signal leaves.

    DuckDB keeps committed transactions in ``<db>.wal`` until a checkpoint, so
    the on-disk pair of a live writer is byte-for-byte what a killed process
    leaves behind. Snapshot that pair, then let the writer close cleanly.
    """
    source = tmp_path / "live.duckdb"
    writer = duckdb.connect(str(source))
    try:
        writer.execute("CREATE TABLE runs (sim_id INTEGER PRIMARY KEY, name TEXT)")
        writer.execute("INSERT INTO runs SELECT i, 'run_' || i FROM range(500) t(i)")
        db_path = tmp_path / "index.duckdb"
        shutil.copyfile(source, db_path)
        shutil.copyfile(source.with_suffix(".duckdb.wal"), db_path.with_suffix(".duckdb.wal"))
    finally:
        writer.close()
    assert db_path.with_suffix(".duckdb.wal").is_file(), "no WAL was left behind"
    return db_path


def test_stale_wal_is_checkpointed_at_open(tmp_path, capture_hmp_logs):
    db_path = _database_killed_mid_write(tmp_path)
    wal_path = db_path.with_suffix(".duckdb.wal")

    # Before recovery the database file alone carries nothing: everything the
    # dead process committed lives in the journal, so any copy of the file
    # loses it.
    orphan = tmp_path / "copy.duckdb"
    shutil.copyfile(db_path, orphan)
    with pytest.raises(duckdb.CatalogException):
        duckdb.connect(str(orphan), read_only=True).execute("SELECT count(*) FROM runs")

    connection = db_retry.connect_with_retry(str(db_path))
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (500,)
    finally:
        connection.close()

    assert not wal_path.exists(), "the stale WAL was not absorbed"
    messages = [r.getMessage() for r in capture_hmp_logs if r.levelno == logging.WARNING]
    assert any("write-ahead log" in m for m in messages), messages


def test_recovered_database_survives_a_file_only_copy(tmp_path):
    db_path = _database_killed_mid_write(tmp_path)
    db_retry.connect_with_retry(str(db_path)).close()

    orphan = tmp_path / "copy.duckdb"
    shutil.copyfile(db_path, orphan)
    connection = duckdb.connect(str(orphan), read_only=True)
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (500,)
    finally:
        connection.close()


def test_read_only_open_leaves_the_wal_untouched(tmp_path, capture_hmp_logs):
    db_path = _database_killed_mid_write(tmp_path)
    wal_path = db_path.with_suffix(".duckdb.wal")

    connection = db_retry.connect_with_retry(str(db_path), read_only=True)
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (500,)
    finally:
        connection.close()

    # A read-only opener cannot write, so it must not claim any recovery.
    assert wal_path.is_file()
    assert not any("write-ahead log" in r.getMessage() for r in capture_hmp_logs)


def test_clean_database_open_reports_nothing(tmp_path, capture_hmp_logs):
    db_path = tmp_path / "clean.duckdb"
    duckdb.connect(str(db_path)).close()

    db_retry.connect_with_retry(str(db_path)).close()

    assert not db_path.with_suffix(".duckdb.wal").exists()
    assert not any("write-ahead log" in r.getMessage() for r in capture_hmp_logs)


def test_checkpoint_failure_is_reported_and_not_fatal(tmp_path, capture_hmp_logs, monkeypatch):
    db_path = _database_killed_mid_write(tmp_path)

    real_execute = duckdb.DuckDBPyConnection.execute

    def _refuse_checkpoint(self, sql, *args, **kwargs):
        if sql.strip().upper() == "CHECKPOINT":
            raise duckdb.TransactionException("Cannot CHECKPOINT: other transactions are active")
        return real_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", _refuse_checkpoint)

    connection = db_retry.connect_with_retry(str(db_path))
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (500,)
    finally:
        connection.close()

    messages = [r.getMessage() for r in capture_hmp_logs if r.levelno == logging.WARNING]
    assert any("could not be checkpointed" in m for m in messages), messages


def test_a_later_open_in_the_same_process_stays_silent(tmp_path, capture_hmp_logs):
    """Only the first open can tell a dead process's journal from a live one."""
    db_path = _database_killed_mid_write(tmp_path)

    first = db_retry.connect_with_retry(str(db_path))
    writer = duckdb.connect(str(db_path))
    try:
        writer.execute("INSERT INTO runs VALUES (9999, 'live')")
        capture_hmp_logs.clear()
        second = db_retry.connect_with_retry(str(db_path))
        second.close()
    finally:
        writer.close()
        first.close()

    assert not any("write-ahead log" in r.getMessage() for r in capture_hmp_logs)
