"""Contract tests for :class:`CacheBackend` and :class:`DuckDBCacheBackend`.

Mirror of ``test_catalog_backend_contract.py`` but targeting the
data-side cache backend. Same shape; any future cache adapter can rerun
the suite against its concrete class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.registry._backend import CacheBackend, DuckDBCacheBackend


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBCacheBackend:
    """Open a DuckDB-backed CacheBackend with a minimal test schema."""
    db = DuckDBCacheBackend(tmp_path / "cache.duckdb")
    db.execute("CREATE TABLE kv (  k VARCHAR PRIMARY KEY,  v INTEGER NOT NULL)")
    yield db
    db.close()


def test_backend_implements_protocol(backend: DuckDBCacheBackend) -> None:
    """DuckDBCacheBackend satisfies the runtime-checkable CacheBackend Protocol."""
    assert isinstance(backend, CacheBackend)


def test_execute_then_fetch_one(backend: DuckDBCacheBackend) -> None:
    """A round-trip insert+fetch_one returns the expected tuple."""
    backend.execute("INSERT INTO kv VALUES (?, ?)", ["a", 1])
    assert backend.fetch_one("SELECT v FROM kv WHERE k = ?", ["a"]) == (1,)


def test_query_returns_dataframe(backend: DuckDBCacheBackend) -> None:
    """query yields a DataFrame with the right shape and column."""
    backend.execute("INSERT INTO kv VALUES (?, ?)", ["a", 1])
    backend.execute("INSERT INTO kv VALUES (?, ?)", ["b", 2])
    df = backend.query("SELECT k FROM kv ORDER BY k")
    assert df.shape == (2, 1)
    assert df["k"].tolist() == ["a", "b"]


def test_fetch_all_empty(backend: DuckDBCacheBackend) -> None:
    """fetch_all on an empty result returns an empty list, not None."""
    rows = backend.fetch_all("SELECT k FROM kv WHERE k = ?", ["missing"])
    assert rows == []


def test_description_after_query(backend: DuckDBCacheBackend) -> None:
    """description() exposes the column names of the latest query."""
    backend.execute("INSERT INTO kv VALUES (?, ?)", ["a", 1])
    backend.fetch_one("SELECT k, v FROM kv WHERE k = ?", ["a"])
    desc = backend.description()
    assert desc is not None
    names = [d[0] for d in desc]
    assert names == ["k", "v"]


def test_transaction_commits(backend: DuckDBCacheBackend) -> None:
    """A clean transaction block commits every inner write."""
    with backend.transaction():
        backend.execute("INSERT INTO kv VALUES (?, ?)", ["x", 1])
        backend.execute("INSERT INTO kv VALUES (?, ?)", ["y", 2])
    rows = backend.fetch_all("SELECT k FROM kv ORDER BY k")
    assert rows == [("x",), ("y",)]


def test_transaction_rolls_back_on_exception(backend: DuckDBCacheBackend) -> None:
    """A raise inside the block rolls back and re-raises the exception."""
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.execute("INSERT INTO kv VALUES (?, ?)", ["z", 1])
            raise RuntimeError("rollback me")
    assert backend.fetch_one("SELECT v FROM kv WHERE k = ?", ["z"]) is None


def test_attach_read_only_cross_db(tmp_path: Path) -> None:
    """attach_read_only loads a sibling DB and detaches on exit."""
    primary = DuckDBCacheBackend(tmp_path / "cache_primary.duckdb")
    secondary = DuckDBCacheBackend(tmp_path / "cache_secondary.duckdb")
    try:
        primary.execute("CREATE TABLE entries (sha VARCHAR PRIMARY KEY)")
        primary.execute("INSERT INTO entries VALUES ('abc')")
        secondary.execute("CREATE TABLE catalog_files (sha VARCHAR PRIMARY KEY, sim VARCHAR)")
        secondary.execute("INSERT INTO catalog_files VALUES ('abc', 'sim1')")
        secondary.close()

        with primary.attach_read_only(tmp_path / "cache_secondary.duckdb", "project"):
            rows = primary.fetch_all(
                "SELECT cf.sim FROM entries e JOIN project.catalog_files cf ON e.sha = cf.sha"
            )
        assert rows == [("sim1",)]
    finally:
        primary.close()


def test_attach_read_only_rejects_bad_alias(tmp_path: Path) -> None:
    """A non-identifier alias is rejected without touching the SQL engine."""
    backend = DuckDBCacheBackend(tmp_path / "cache.duckdb")
    try:
        with pytest.raises(ValueError):
            with backend.attach_read_only(tmp_path / "other.duckdb", "bad alias"):
                pass
    finally:
        backend.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    """Double-close on an owned backend stays safe."""
    backend = DuckDBCacheBackend(tmp_path / "cache.duckdb")
    backend.close()
    backend.close()


def test_from_connection_does_not_own(tmp_path: Path) -> None:
    """from_connection wraps a borrowed connection without closing it."""
    import duckdb

    raw = duckdb.connect(str(tmp_path / "shared.duckdb"))
    try:
        adapter = DuckDBCacheBackend.from_connection(raw, path=tmp_path / "shared.duckdb")
        adapter.execute("CREATE TABLE t (id INTEGER)")
        adapter.close()
        # Underlying connection must still be alive after adapter.close().
        raw.execute("INSERT INTO t VALUES (1)")
        assert raw.execute("SELECT COUNT(*) FROM t").fetchone() == (1,)
    finally:
        raw.close()
