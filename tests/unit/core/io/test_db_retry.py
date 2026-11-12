"""Opening a DuckDB catalog: lock contention is waited out, anything else is told at once."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.io import db_retry

LOCK_MESSAGE = (
    'Could not set lock on file "catalog.duckdb": Conflicting lock is held by another process'
)


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(db_retry.time, "sleep", waited.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda _a, _b: 0.0)
    return waited


@pytest.fixture(autouse=True)
def _forget_inspected_paths(monkeypatch) -> None:
    monkeypatch.setattr(db_retry, "_WAL_SEEN_PATHS", set())


def _connect_failing(monkeypatch, failures: list[Exception]) -> list[tuple]:
    """Make duckdb.connect raise the given errors in order, then open for real."""
    real_connect = duckdb.connect
    calls: list[tuple] = []

    def connect(path, **kwargs):
        calls.append((path, kwargs))
        if failures:
            raise failures.pop(0)
        return real_connect(path, **kwargs)

    monkeypatch.setattr(db_retry.duckdb, "connect", connect)
    return calls


def test_lock_waited_out_with_backoff(monkeypatch, sleeps, tmp_path: Path) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException(LOCK_MESSAGE)] * 3)

    con = db_retry.connect_with_retry(str(tmp_path / "c.duckdb"), backoff=0.1, max_backoff=0.3)

    assert con.execute("select 42").fetchone() == (42,)
    assert len(calls) == 4
    assert sleeps == pytest.approx([0.1, 0.2, 0.3])  # doubled, then held at the cap
    con.close()


def test_lock_that_never_clears(monkeypatch, sleeps) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException(LOCK_MESSAGE)] * 10)

    with pytest.raises(duckdb.IOException, match="Conflicting lock"):
        db_retry.connect_with_retry(":memory:", retries=4, backoff=0.01)

    assert len(calls) == 4
    assert len(sleeps) == 3  # no wait after the last attempt


def test_other_io_error_not_retried(monkeypatch, sleeps) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException("No space left on device")])

    with pytest.raises(duckdb.IOException, match="No space left"):
        db_retry.connect_with_retry(":memory:")

    assert len(calls) == 1
    assert sleeps == []


def test_other_mode_is_a_conflict(monkeypatch, tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.duckdb"
    catalog.write_bytes(b"x")
    _connect_failing(
        monkeypatch,
        [
            duckdb.ConnectionException(
                "Can't open a connection to same database file with a different configuration"
            )
        ],
    )

    with pytest.raises(WriteConflictError, match="another mode"):
        db_retry.connect_with_retry(str(catalog))


def test_missing_catalog_keeps_error(monkeypatch) -> None:
    _connect_failing(monkeypatch, [duckdb.IOException("Cannot open file: no such file")])

    with pytest.raises(duckdb.IOException, match="no such file"):
        db_retry.connect_with_retry("/nonexistent/folder/catalog.duckdb", read_only=True)


def test_attached_path_precreate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "held.duckdb"
    holder = duckdb.connect(":memory:")
    holder.execute(f"ATTACH '{path}'")
    path.unlink()  # the entry outlives the file

    db_retry._precreate_with_block_size(str(path), 16384)

    assert not path.exists()
    holder.close()


def test_precreate_error_not_hidden(tmp_path: Path) -> None:
    with pytest.raises(duckdb.Error):
        db_retry._precreate_with_block_size(str(tmp_path / "c.duckdb"), 1234)  # not a power of two


def test_wal_not_checkpointed_warns(caplog) -> None:
    class Refusing:
        def execute(self, _sql: str) -> None:
            raise duckdb.Error("torn journal")

    with caplog.at_level("WARNING"):
        db_retry._absorb_stale_wal(Refusing(), "c.duckdb", 2048)

    assert "could not be checkpointed" in caplog.text


def test_wal_checkpointed_is_recovered(caplog) -> None:
    class Accepting:
        def execute(self, _sql: str) -> None:
            return None

    with caplog.at_level("WARNING"):
        db_retry._absorb_stale_wal(Accepting(), "c.duckdb", 2048)

    assert "Recovered a left-over" in caplog.text


def test_jitter_adds_a_quarter(monkeypatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr(db_retry.time, "sleep", waited.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda _a, b: b)

    slept = db_retry._sleep_with_jitter(2.0)

    assert slept == pytest.approx(2.5)
    assert waited == [slept]


def test_decorator_retries_then_succeeds(sleeps) -> None:
    attempts: list[int] = []

    @db_retry.with_lock_retry(retries=5, backoff=0.1)
    def write(value: int) -> int:
        attempts.append(1)
        if len(attempts) < 3:
            raise duckdb.IOException(LOCK_MESSAGE)
        return value * 2

    assert write(21) == 42
    assert len(attempts) == 3
    assert sleeps == pytest.approx([0.1, 0.2])


def test_decorator_gives_up(sleeps) -> None:
    attempts: list[int] = []

    @db_retry.with_lock_retry(retries=3, backoff=0.01)
    def write() -> None:
        attempts.append(1)
        raise duckdb.IOException(LOCK_MESSAGE)

    with pytest.raises(duckdb.IOException, match="Conflicting lock"):
        write()

    assert len(attempts) == 3
    assert len(sleeps) == 2


def test_decorator_skips_other_errors(sleeps) -> None:
    attempts: list[int] = []

    @db_retry.with_lock_retry(retries=3)
    def write() -> None:
        attempts.append(1)
        raise duckdb.IOException("No space left on device")

    with pytest.raises(duckdb.IOException, match="No space"):
        write()

    assert len(attempts) == 1
    assert sleeps == []


def test_attach_read_only(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other.duckdb"
    with duckdb.connect(str(other)) as seed:
        seed.execute("CREATE TABLE t AS SELECT 7 AS v")
    connection = duckdb.connect(":memory:")

    with db_retry.attach_read_only(connection, other, "snap"):
        assert connection.execute("SELECT v FROM snap.t").fetchone() == (7,)
    with pytest.raises(duckdb.Error):
        connection.execute("SELECT v FROM snap.t")

    with pytest.raises(ValueError, match="Invalid attach alias"):
        with db_retry.attach_read_only(connection, other, "bad alias"):
            pass
