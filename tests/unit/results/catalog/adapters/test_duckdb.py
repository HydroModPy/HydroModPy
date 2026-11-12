"""The SQL adapter of the catalog, ``DuckDBBackend``, played without the catalog facade.

Its surface is execute, query, fetch_one, fetch_all, insert, upsert, transaction and
attach_read_only, on one table ``kv`` of a key, an integer and a label.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.layout import CATALOG_FILENAME
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBBackend:
    db = DuckDBBackend(tmp_path / CATALOG_FILENAME)
    db.execute("CREATE TABLE kv (  k VARCHAR PRIMARY KEY,  v INTEGER NOT NULL,  label VARCHAR)")
    yield db
    db.close()


def test_backend_opens_its_file_and_reports_its_path(
    tmp_path: Path, backend: DuckDBBackend
) -> None:
    """The backend creates the file it was given and serves it on a live connection."""
    assert backend.path == tmp_path / CATALOG_FILENAME
    assert backend.path.is_file()
    assert backend.connection.execute("SELECT count(*) FROM kv").fetchone() == (0,)


def test_execute_then_query_roundtrip(backend: DuckDBBackend) -> None:
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    df = backend.query("SELECT k, v FROM kv WHERE k = ?", ["a"])
    assert df.shape == (1, 2)
    assert df.iloc[0]["k"] == "a"
    assert int(df.iloc[0]["v"]) == 1


def test_fetch_one_returns_tuple_or_none(backend: DuckDBBackend) -> None:
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    row = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["a"])
    assert row == ("a", 1)
    missing = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["missing"])
    assert missing is None


def test_fetch_all_returns_tuples(backend: DuckDBBackend) -> None:
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["b", 2])
    rows = backend.fetch_all("SELECT k FROM kv ORDER BY k")
    assert rows == [("a",), ("b",)]


def test_query_empty_returns_empty_dataframe(backend: DuckDBBackend) -> None:
    df = backend.query("SELECT * FROM kv")
    assert df.empty


def test_insert_writes_row(backend: DuckDBBackend) -> None:
    backend.insert("kv", {"k": "x", "v": 10})
    row = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["x"])
    assert row == ("x", 10)


# One row per refused insert: the table and the row.
INSERT_REFUSALS = [
    pytest.param("kv", {}, id="empty row"),
    pytest.param(
        '"kv"; DROP TABLE kv;--', {"k": "x", "v": 1}, id="table name is not an identifier"
    ),
]


@pytest.mark.parametrize(("table", "row"), INSERT_REFUSALS)
def test_insert_refusals(backend: DuckDBBackend, table, row) -> None:
    with pytest.raises(ValueError):
        backend.insert(table, row)


def test_upsert_insert_path(backend: DuckDBBackend) -> None:
    backend.upsert("kv", {"k": "new", "v": 1, "label": "first"}, key_cols=["k"])
    row = backend.fetch_one("SELECT v, label FROM kv WHERE k = ?", ["new"])
    assert row == (1, "first")


def test_upsert_update_path(backend: DuckDBBackend) -> None:
    backend.insert("kv", {"k": "key", "v": 1, "label": "old"})
    backend.upsert("kv", {"k": "key", "v": 9, "label": "new"}, key_cols=["k"])
    row = backend.fetch_one("SELECT v, label FROM kv WHERE k = ?", ["key"])
    assert row == (9, "new")


# One row per refused upsert: the row and the key columns.
UPSERT_REFUSALS = [
    pytest.param({"v": 1}, ["k"], id="key column absent from the row"),
    pytest.param({"k": "x", "v": 1}, [], id="no key column"),
]


@pytest.mark.parametrize(("row", "key_cols"), UPSERT_REFUSALS)
def test_upsert_refusals(backend: DuckDBBackend, row, key_cols) -> None:
    with pytest.raises(ValueError):
        backend.upsert("kv", row, key_cols=key_cols)


def test_transaction_commits_on_success(backend: DuckDBBackend) -> None:
    with backend.transaction():
        backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["t1", 1])
        backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["t2", 2])
    rows = backend.fetch_all("SELECT k FROM kv ORDER BY k")
    assert rows == [("t1",), ("t2",)]


def test_transaction_rolls_back_on_exception(backend: DuckDBBackend) -> None:
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["x", 1])
            raise RuntimeError("boom")
    row = backend.fetch_one("SELECT v FROM kv WHERE k = ?", ["x"])
    assert row is None


def test_attach_read_only_cross_db_join(tmp_path: Path) -> None:
    primary = DuckDBBackend(tmp_path / "primary.duckdb")
    secondary = DuckDBBackend(tmp_path / "secondary.duckdb")
    try:
        primary.execute("CREATE TABLE local (sha VARCHAR PRIMARY KEY, label VARCHAR)")
        primary.execute("INSERT INTO local VALUES ('abc', 'hello')")
        primary.execute("INSERT INTO local VALUES ('def', 'world')")
        secondary.execute("CREATE TABLE remote (sha VARCHAR PRIMARY KEY, meta INTEGER)")
        secondary.execute("INSERT INTO remote VALUES ('abc', 7)")
        secondary.close()

        with primary.attach_read_only(tmp_path / "secondary.duckdb", "snap"):
            rows = primary.fetch_all(
                "SELECT l.label, r.meta FROM local l JOIN snap.remote r ON l.sha = r.sha"
            )
        assert rows == [("hello", 7)]
    finally:
        primary.close()


def test_attach_read_only_rejects_bad_alias(tmp_path: Path) -> None:
    backend = DuckDBBackend(tmp_path / "primary.duckdb")
    try:
        with pytest.raises(ValueError):
            with backend.attach_read_only(tmp_path / "secondary.duckdb", "bad alias"):
                pass
    finally:
        backend.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    backend = DuckDBBackend(tmp_path / "primary.duckdb")
    backend.close()
    # Second close() must not raise.
    backend.close()


def test_from_connection_does_not_own(tmp_path: Path) -> None:
    import duckdb

    raw = duckdb.connect(str(tmp_path / "shared.duckdb"))
    try:
        adapter = DuckDBBackend.from_connection(raw, path=tmp_path / "shared.duckdb")
        adapter.execute("CREATE TABLE t (id INTEGER)")
        adapter.close()
        # The underlying connection must still work after the adapter close.
        raw.execute("INSERT INTO t VALUES (1)")
        row = raw.execute("SELECT COUNT(*) FROM t").fetchone()
        assert row == (1,)
    finally:
        raw.close()
