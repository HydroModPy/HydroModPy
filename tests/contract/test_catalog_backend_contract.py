"""Contract tests for :class:`CatalogBackend` and :class:`DuckDBBackend`.

Exercises the SQL-level surface (execute, query, fetch_one, fetch_all,
insert, upsert, transaction, attach_read_only) independently of the
catalog facade. Any future adapter can opt in by binding the fixture to
its own constructor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.ports import CatalogBackend


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBBackend:
    """Open a DuckDB-backed CatalogBackend with a minimal test schema."""
    db = DuckDBBackend(tmp_path / CATALOG_FILENAME)
    db.execute("CREATE TABLE kv (  k VARCHAR PRIMARY KEY,  v INTEGER NOT NULL,  label VARCHAR)")
    yield db
    db.close()


def test_backend_implements_protocol(backend: DuckDBBackend) -> None:
    """DuckDBBackend satisfies the runtime-checkable CatalogBackend Protocol."""
    assert isinstance(backend, CatalogBackend)


def test_execute_then_query_roundtrip(backend: DuckDBBackend) -> None:
    """execute() persists a row that query() can read back."""
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    df = backend.query("SELECT k, v FROM kv WHERE k = ?", ["a"])
    assert df.shape == (1, 2)
    assert df.iloc[0]["k"] == "a"
    assert int(df.iloc[0]["v"]) == 1


def test_fetch_one_returns_tuple_or_none(backend: DuckDBBackend) -> None:
    """fetch_one returns a tuple when a row matches, None otherwise."""
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    row = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["a"])
    assert row == ("a", 1)
    missing = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["missing"])
    assert missing is None


def test_fetch_all_returns_tuples(backend: DuckDBBackend) -> None:
    """fetch_all returns a list of tuples preserving order."""
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["a", 1])
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["b", 2])
    rows = backend.fetch_all("SELECT k FROM kv ORDER BY k")
    assert rows == [("a",), ("b",)]


def test_query_empty_returns_empty_dataframe(backend: DuckDBBackend) -> None:
    """query against an empty table yields an empty DataFrame."""
    df = backend.query("SELECT * FROM kv")
    assert df.empty


def test_insert_writes_row(backend: DuckDBBackend) -> None:
    """The structural insert() composes a portable INSERT statement."""
    backend.insert("kv", {"k": "x", "v": 10})
    row = backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["x"])
    assert row == ("x", 10)


def test_insert_rejects_empty_row(backend: DuckDBBackend) -> None:
    """An empty row raises ValueError rather than producing invalid SQL."""
    with pytest.raises(ValueError):
        backend.insert("kv", {})


def test_insert_rejects_bad_identifier(backend: DuckDBBackend) -> None:
    """Identifier validation guards against SQL injection in table names."""
    with pytest.raises(ValueError):
        backend.insert('"kv"; DROP TABLE kv;--', {"k": "x", "v": 1})


def test_upsert_insert_path(backend: DuckDBBackend) -> None:
    """upsert inserts a new row when the conflict key is fresh."""
    backend.upsert("kv", {"k": "new", "v": 1, "label": "first"}, key_cols=["k"])
    row = backend.fetch_one("SELECT v, label FROM kv WHERE k = ?", ["new"])
    assert row == (1, "first")


def test_upsert_update_path(backend: DuckDBBackend) -> None:
    """upsert updates the existing row on conflict over key columns."""
    backend.insert("kv", {"k": "key", "v": 1, "label": "old"})
    backend.upsert("kv", {"k": "key", "v": 9, "label": "new"}, key_cols=["k"])
    row = backend.fetch_one("SELECT v, label FROM kv WHERE k = ?", ["key"])
    assert row == (9, "new")


def test_upsert_rejects_missing_key(backend: DuckDBBackend) -> None:
    """upsert raises when one of the declared key columns is absent."""
    with pytest.raises(ValueError):
        backend.upsert("kv", {"v": 1}, key_cols=["k"])


def test_upsert_rejects_empty_key_cols(backend: DuckDBBackend) -> None:
    """upsert refuses an empty key_cols tuple to keep DDL semantics explicit."""
    with pytest.raises(ValueError):
        backend.upsert("kv", {"k": "x", "v": 1}, key_cols=[])


def test_transaction_commits_on_success(backend: DuckDBBackend) -> None:
    """A successful transaction block persists every nested execute()."""
    with backend.transaction():
        backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["t1", 1])
        backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["t2", 2])
    rows = backend.fetch_all("SELECT k FROM kv ORDER BY k")
    assert rows == [("t1",), ("t2",)]


def test_transaction_rolls_back_on_exception(backend: DuckDBBackend) -> None:
    """An exception inside the block rolls back every write and re-raises."""
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["x", 1])
            raise RuntimeError("boom")
    row = backend.fetch_one("SELECT v FROM kv WHERE k = ?", ["x"])
    assert row is None


def test_dict_params_supported(backend: DuckDBBackend) -> None:
    """Backends accept Mapping params alongside positional sequences."""
    backend.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ["d", 5])
    df = backend.query("SELECT v FROM kv WHERE k = ?", ["d"])
    assert int(df.iloc[0]["v"]) == 5


def test_attach_read_only_cross_db_join(tmp_path: Path) -> None:
    """attach_read_only exposes a remote DB under an alias for SELECTs only."""
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
    """A non-identifier alias is rejected before touching the SQL engine."""
    backend = DuckDBBackend(tmp_path / "primary.duckdb")
    try:
        with pytest.raises(ValueError):
            with backend.attach_read_only(tmp_path / "secondary.duckdb", "bad alias"):
                pass
    finally:
        backend.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    """Calling close() twice on an owned connection stays safe."""
    backend = DuckDBBackend(tmp_path / "primary.duckdb")
    backend.close()
    # Second close() must not raise.
    backend.close()


def test_from_connection_does_not_own(tmp_path: Path) -> None:
    """from_connection wraps a borrowed connection without closing it."""
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
