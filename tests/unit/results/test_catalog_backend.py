"""The DuckDB adapter of the catalog index: reads, writes, transactions, and its refusals.

Each public method runs on a temporary DuckDB file, so parameter binding,
commit, rollback and the upsert key checks are exercised for real.
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


def test_fetch_one(backend: DuckDBBackend) -> None:
    assert backend.fetch_one("SELECT 7, 'q'") == (7, "q")


REFUSALS = [
    pytest.param("CREATE TABLE t (a INT)", "insert", ("t", {}), {}, id="insert of an empty row"),
    pytest.param(
        "CREATE TABLE t (a INT PRIMARY KEY, b VARCHAR)",
        "upsert",
        ("t", {"b": "only"}),
        {"key_cols": ["a"]},
        id="upsert without its key",
    ),
    pytest.param(
        "CREATE TABLE t (a INT, b VARCHAR)",
        "upsert",
        ("t", {"a": 1, "b": "x"}),
        {"key_cols": []},
        id="upsert with no key columns",
    ),
]


@pytest.mark.parametrize(("ddl", "method", "args", "kwargs"), REFUSALS)
def test_refusals(backend: DuckDBBackend, ddl, method, args, kwargs) -> None:
    backend.execute(ddl)
    with pytest.raises(ValueError):
        getattr(backend, method)(*args, **kwargs)


def test_transaction_commit(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with backend.transaction():
        backend.execute("INSERT INTO t VALUES (?)", [1])
        backend.execute("INSERT INTO t VALUES (?)", [2])
    rows = backend.fetch_all("SELECT a FROM t ORDER BY a")
    assert rows == [(1,), (2,)]


def test_transaction_rollback(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT)")
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.execute("INSERT INTO t VALUES (?)", [99])
            raise RuntimeError("boom")
    rows = backend.fetch_all("SELECT a FROM t")
    assert rows == []


def test_from_connection_stays_open(tmp_path: Path) -> None:
    import duckdb

    conn = duckdb.connect(str(tmp_path / "c.duckdb"))
    b = DuckDBBackend.from_connection(conn)
    assert isinstance(b, DuckDBBackend)
    b.execute("CREATE TABLE t (a INT)")
    b.close()  # owns_connection=False, no-op
    conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT * FROM t").fetchall() == [(1,)]
    conn.close()


def test_query_with_named_params(backend: DuckDBBackend) -> None:
    backend.execute("CREATE TABLE t (a INT, b VARCHAR)")
    backend.execute("INSERT INTO t VALUES (?, ?)", [1, "u"])
    backend.execute("INSERT INTO t VALUES (?, ?)", [2, "v"])
    df = backend.query("SELECT a FROM t WHERE b = $b", {"b": "v"})
    assert len(df) == 1
    assert df.iloc[0, 0] == 2
