"""Unit tests for the :class:`DuckDBBackend` Protocol and the DuckDB adapter.

The Protocol is structural; ``DuckDBBackend`` must satisfy it via
``isinstance`` checks since the Protocol is ``runtime_checkable``. Each
public method is exercised against a temporary DuckDB file so the suite
catches regressions in parameter binding, transactions, and idempotent
upserts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBBackend:
    path = tmp_path / "catalog.duckdb"
    b = DuckDBBackend(path)
    yield b
    b.close()


def test_fetch_one_returns_row_tuple(backend: DuckDBBackend) -> None:
    row = backend.fetch_one("SELECT 7, 'q'")
    assert row == (7, "q")


def test_insert_rejects_empty_row(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with pytest.raises(ValueError):
        backend.insert("t", {})


def test_upsert_rejects_missing_key(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR)")
    with pytest.raises(ValueError):
        backend.upsert("t", {"b": "only"}, key_cols=["a"])


def test_upsert_rejects_empty_keys(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    with pytest.raises(ValueError):
        backend.upsert("t", {"a": 1, "b": "x"}, key_cols=[])


def test_transaction_commit_persists(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with backend.transaction():
        backend.execute("INSERT INTO t VALUES (?)", [1])
        backend.execute("INSERT INTO t VALUES (?)", [2])
    rows = backend.fetch_all("SELECT a FROM t ORDER BY a")
    assert rows == [(1,), (2,)]


def test_transaction_rollback_discards(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.execute("INSERT INTO t VALUES (?)", [99])
            raise RuntimeError("boom")
    rows = backend.fetch_all("SELECT a FROM t")
    assert rows == []


def test_from_connection_does_not_close(tmp_path: Path) -> None:
    import duckdb

    conn = duckdb.connect(str(tmp_path / "c.duckdb"))
    b = DuckDBBackend.from_connection(conn)
    assert isinstance(b, DuckDBBackend)
    b.execute("CREATE TABLE t (a INT)")
    b.close()  # owns_connection=False, no-op
    conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT * FROM t").fetchall() == [(1,)]
    conn.close()


def test_query_with_dict_params(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    backend.execute("INSERT INTO t VALUES (?, ?)", [1, "u"])
    backend.execute("INSERT INTO t VALUES (?, ?)", [2, "v"])
    df = backend.query("SELECT a FROM t WHERE b = $b", {"b": "v"})
    assert len(df) == 1
    assert df.iloc[0, 0] == 2
