"""Unit tests for the :class:`CatalogBackend` Protocol and the DuckDB adapter.

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
from hydromodpy.results.catalog.ports import CatalogBackend


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBBackend:
    path = tmp_path / "catalog.duckdb"
    b = DuckDBBackend(path)
    yield b
    b.close()


def test_isinstance_protocol(backend: DuckDBBackend) -> None:
    assert isinstance(backend, CatalogBackend)


def test_query_returns_dataframe(backend: DuckDBBackend) -> None:
    df = backend.query("SELECT 1 AS a, 'x' AS b")
    assert df.shape == (1, 2)
    assert list(df.columns) == ["a", "b"]
    assert df.iloc[0, 0] == 1
    assert df.iloc[0, 1] == "x"


def test_query_with_positional_params(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    backend.execute("INSERT INTO t VALUES (?, ?)", [1, "alpha"])
    backend.execute("INSERT INTO t VALUES (?, ?)", [2, "beta"])
    df = backend.query("SELECT a, b FROM t WHERE a >= ? ORDER BY a", [2])
    assert len(df) == 1
    assert df.iloc[0, 0] == 2


def test_execute_runs_ddl_dml(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    backend.execute("INSERT INTO t VALUES (10)")
    backend.execute("UPDATE t SET a = 20")
    df = backend.query("SELECT * FROM t")
    assert df.iloc[0, 0] == 20


def test_fetch_one_returns_row_tuple(backend: DuckDBBackend) -> None:
    row = backend.fetch_one("SELECT 7, 'q'")
    assert row == (7, "q")


def test_fetch_one_returns_none_on_empty(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    row = backend.fetch_one("SELECT * FROM t LIMIT 1")
    assert row is None


def test_fetch_all_returns_list_of_tuples(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    backend.execute("INSERT INTO t VALUES (1), (2), (3)")
    rows = backend.fetch_all("SELECT a FROM t ORDER BY a")
    assert rows == [(1,), (2,), (3,)]


def test_insert_basic(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    backend.insert("t", {"a": 5, "b": "hello"})
    rows = backend.fetch_all("SELECT * FROM t")
    assert rows == [(5, "hello")]


def test_insert_rejects_empty_row(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with pytest.raises(ValueError):
        backend.insert("t", {})


def test_upsert_on_conflict_updates(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR)")
    backend.upsert("t", {"a": 1, "b": "x"}, key_cols=["a"])
    backend.upsert("t", {"a": 1, "b": "y"}, key_cols=["a"])
    rows = backend.fetch_all("SELECT * FROM t")
    assert rows == [(1, "y")]


def test_upsert_inserts_when_no_conflict(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR)")
    backend.upsert("t", {"a": 1, "b": "x"}, key_cols=["a"])
    backend.upsert("t", {"a": 2, "b": "y"}, key_cols=["a"])
    rows = backend.fetch_all("SELECT * FROM t ORDER BY a")
    assert rows == [(1, "x"), (2, "y")]


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


def test_close_releases_resources(tmp_path: Path) -> None:
    b = DuckDBBackend(tmp_path / "c.duckdb")
    b.execute("CREATE TABLE t (a INT)")
    b.close()
    # After close, calling fetch should raise (driver-specific). We assert
    # that close itself does not raise and is idempotent.
    b.close()


def test_from_connection_does_not_close(tmp_path: Path) -> None:
    import duckdb

    conn = duckdb.connect(str(tmp_path / "c.duckdb"))
    b = DuckDBBackend.from_connection(conn)
    assert isinstance(b, CatalogBackend)
    b.execute("CREATE TABLE t (a INT)")
    b.close()  # owns_connection=False, no-op
    conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT * FROM t").fetchall() == [(1,)]
    conn.close()


def test_ensure_schema_creates_catalog_v2_tables(tmp_path: Path) -> None:
    b = DuckDBBackend(tmp_path / "c.duckdb")
    try:
        b.ensure_schema()
        # Spot-check a handful of v2 catalog tables.
        names = {
            r[0]
            for r in b.fetch_all(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            )
        }
        for expected in ("simulations", "solvers", "statuses", "metrics", "parameters"):
            assert expected in names
    finally:
        b.close()


def test_query_with_dict_params(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    backend.execute("INSERT INTO t VALUES (?, ?)", [1, "u"])
    backend.execute("INSERT INTO t VALUES (?, ?)", [2, "v"])
    df = backend.query("SELECT a FROM t WHERE b = $b", {"b": "v"})
    assert len(df) == 1
    assert df.iloc[0, 0] == 2
