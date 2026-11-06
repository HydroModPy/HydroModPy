"""Opening a DuckDB catalog: lock contention is waited out, anything else is told at once."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import CatalogUnreadableError, WriteConflictError
from hydromodpy.core.io import db_retry

LOCK_MESSAGE = (
    'Could not set lock on file "catalog.duckdb": Conflicting lock is held by another process'
)


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record the waits instead of sleeping them."""
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


def test_a_lock_held_for_a_few_attempts_is_waited_out_with_a_growing_delay(
    monkeypatch, sleeps, tmp_path: Path
) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException(LOCK_MESSAGE)] * 3)

    con = db_retry.connect_with_retry(str(tmp_path / "c.duckdb"), backoff=0.1, max_backoff=0.3)

    assert con.execute("select 42").fetchone() == (42,)
    assert len(calls) == 4
    assert sleeps == pytest.approx([0.1, 0.2, 0.3])  # doubled, then held at the cap
    con.close()


def test_a_lock_that_never_clears_ends_in_the_lock_error_after_every_attempt(
    monkeypatch, sleeps
) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException(LOCK_MESSAGE)] * 10)

    with pytest.raises(duckdb.IOException, match="Conflicting lock"):
        db_retry.connect_with_retry(":memory:", retries=4, backoff=0.01)

    assert len(calls) == 4
    assert len(sleeps) == 3  # no wait after the last attempt


@pytest.mark.parametrize(
    "message",
    [
        "Conflicting lock is held",
        "held by another process",
        "Le fichier est utilisé par un autre processus",
        "Resource temporarily unavailable",
        "database is locked",
    ],
)
def test_the_lock_messages_of_duckdb_and_of_the_system_are_recognised(message: str) -> None:
    assert db_retry._is_lock_contention(duckdb.IOException(message))


def test_an_io_error_that_is_not_a_lock_is_not_waited_for(monkeypatch, sleeps) -> None:
    calls = _connect_failing(monkeypatch, [duckdb.IOException("No space left on device")])

    with pytest.raises(duckdb.IOException, match="No space left"):
        db_retry.connect_with_retry(":memory:")

    assert len(calls) == 1
    assert sleeps == []


def test_a_damaged_catalog_that_exists_is_named_as_unreadable(
    monkeypatch, sleeps, tmp_path: Path
) -> None:
    damaged = tmp_path / "catalog.duckdb"
    damaged.write_bytes(b"not a database")
    _connect_failing(monkeypatch, [duckdb.Error("Invalid database file")])

    with pytest.raises(CatalogUnreadableError):
        db_retry.connect_with_retry(str(damaged))

    assert sleeps == []


def test_a_catalog_already_open_in_another_mode_is_told_as_a_conflict_not_as_damage(
    monkeypatch, tmp_path: Path
) -> None:
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


def test_a_catalog_that_does_not_exist_keeps_the_original_error(monkeypatch) -> None:
    _connect_failing(monkeypatch, [duckdb.IOException("Cannot open file: no such file")])

    with pytest.raises(duckdb.IOException, match="no such file"):
        db_retry.connect_with_retry("/nonexistent/folder/catalog.duckdb", read_only=True)


def test_the_options_of_the_caller_reach_duckdb(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "c.duckdb"
    duckdb.connect(str(path)).close()
    calls = _connect_failing(monkeypatch, [])

    db_retry.connect_with_retry(str(path), read_only=True).close()

    assert calls == [(str(path), {"read_only": True})]


def test_a_new_catalog_is_created_with_the_small_block_size_asked(tmp_path: Path) -> None:
    path = tmp_path / "small.duckdb"

    con = db_retry.connect_with_retry(str(path), block_size=db_retry.HMP_DUCKDB_BLOCK_SIZE)
    con.close()

    with duckdb.connect(str(path), read_only=True) as check:
        row = check.execute("select block_size from pragma_database_size()").fetchone()
    assert row == (db_retry.HMP_DUCKDB_BLOCK_SIZE,)


def test_the_block_size_is_ignored_for_a_file_that_already_exists(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "old.duckdb"
    duckdb.connect(str(path)).close()
    precreated: list[str] = []
    monkeypatch.setattr(db_retry, "_precreate_with_block_size", lambda p, _b: precreated.append(p))

    db_retry.connect_with_retry(str(path), block_size=16384).close()

    assert precreated == []


def test_a_path_still_attached_in_this_process_does_not_stop_the_block_size_pre_create(
    tmp_path: Path,
) -> None:
    path = tmp_path / "held.duckdb"
    holder = duckdb.connect(":memory:")
    holder.execute(f"ATTACH '{path}'")
    path.unlink()  # the entry outlives the file

    db_retry._precreate_with_block_size(str(path), 16384)

    assert not path.exists()
    holder.close()


def test_another_binder_error_during_the_pre_create_is_not_hidden(tmp_path: Path) -> None:
    with pytest.raises(duckdb.Error):
        db_retry._precreate_with_block_size(str(tmp_path / "c.duckdb"), 1234)  # not a power of two


def test_the_wal_left_by_a_dead_process_is_reported_only_on_the_first_open(tmp_path: Path) -> None:
    path = tmp_path / "c.duckdb"
    Path(f"{path}.wal").write_bytes(b"x" * 2048)

    first = db_retry._stale_wal_size(str(path))
    second = db_retry._stale_wal_size(str(path))

    assert (first, second) == (2048, None)


@pytest.mark.parametrize("path", [":memory:", ""])
def test_an_in_memory_database_has_no_wal_to_look_for(path: str) -> None:
    assert db_retry._stale_wal_size(path) is None


def test_a_database_without_wal_reports_nothing(tmp_path: Path) -> None:
    assert db_retry._stale_wal_size(str(tmp_path / "c.duckdb")) is None


def test_a_wal_found_at_open_is_checkpointed_once(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "c.duckdb"
    duckdb.connect(str(path)).close()
    Path(f"{path}.wal").write_bytes(b"")
    statements: list[str] = []

    class Recorder:
        def execute(self, sql: str) -> None:
            statements.append(sql)

    monkeypatch.setattr(db_retry, "_stale_wal_size", lambda _p: 4096)
    monkeypatch.setattr(db_retry.duckdb, "connect", lambda *_a, **_k: Recorder())

    db_retry.connect_with_retry(str(path))

    assert statements == ["CHECKPOINT"]


def test_a_wal_that_cannot_be_checkpointed_is_a_warning_and_the_connection_is_kept(caplog) -> None:
    class Refusing:
        def execute(self, _sql: str) -> None:
            raise duckdb.Error("torn journal")

    with caplog.at_level("WARNING"):
        db_retry._absorb_stale_wal(Refusing(), "c.duckdb", 2048)

    assert "could not be checkpointed" in caplog.text


def test_a_wal_checkpointed_is_reported_as_recovered(caplog) -> None:
    class Accepting:
        def execute(self, _sql: str) -> None:
            return None

    with caplog.at_level("WARNING"):
        db_retry._absorb_stale_wal(Accepting(), "c.duckdb", 2048)

    assert "Recovered a left-over" in caplog.text


def test_the_wait_between_attempts_is_the_delay_plus_at_most_a_quarter(monkeypatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr(db_retry.time, "sleep", waited.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda _a, b: b)

    slept = db_retry._sleep_with_jitter(2.0)

    assert slept == pytest.approx(2.5)
    assert waited == [slept]


# ---- with_lock_retry --------------------------------------------------------


def test_a_method_that_meets_a_lock_twice_succeeds_on_the_third_attempt(sleeps) -> None:
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


def test_a_method_blocked_for_good_raises_the_lock_error_after_its_attempts(sleeps) -> None:
    attempts: list[int] = []

    @db_retry.with_lock_retry(retries=3, backoff=0.01)
    def write() -> None:
        attempts.append(1)
        raise duckdb.IOException(LOCK_MESSAGE)

    with pytest.raises(duckdb.IOException, match="Conflicting lock"):
        write()

    assert len(attempts) == 3
    assert len(sleeps) == 2


def test_a_method_failing_for_another_reason_is_not_retried(sleeps) -> None:
    attempts: list[int] = []

    @db_retry.with_lock_retry(retries=3)
    def write() -> None:
        attempts.append(1)
        raise duckdb.IOException("No space left on device")

    with pytest.raises(duckdb.IOException, match="No space"):
        write()

    assert len(attempts) == 1
    assert sleeps == []


def test_the_decorated_method_keeps_its_name() -> None:
    @db_retry.with_lock_retry()
    def commit_catalog() -> None: ...

    assert commit_catalog.__name__ == "commit_catalog"


def test_an_attached_database_is_readable_inside_the_block_and_detached_after(
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
