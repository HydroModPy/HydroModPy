"""Tests for the idle-release DuckDB handle owned by :class:`Catalog`.

A catalog stays open for the whole run, so the connection must not hold the
DuckDB file lock while nothing uses it: otherwise no other process can read
the catalog during a solve.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hydromodpy.results.catalog import Catalog


@pytest.fixture
def catalog(tmp_path: Path):
    cat = Catalog(tmp_path / "ws")
    try:
        yield cat
    finally:
        cat.close()


def test_idle_release_drops_the_database_lock(catalog: Catalog) -> None:
    """Releasing the idle handle frees the file for another opener."""
    db_path = str(catalog.catalog_path)
    with pytest.raises(duckdb.Error):
        duckdb.connect(db_path, read_only=True)

    assert catalog._db.release_if_idle(0.0) is True

    probe = duckdb.connect(db_path, read_only=True)
    probe.close()


def test_reopen_is_transparent_and_keeps_data(catalog: Catalog) -> None:
    """A statement after a release reopens the file and still sees the rows."""
    catalog.connection.execute("CREATE TABLE probe (i INTEGER)")
    catalog.connection.execute("INSERT INTO probe VALUES (7)")
    assert catalog._db.release_if_idle(0.0) is True

    row = catalog.connection.execute("SELECT i FROM probe").fetchone()
    assert row == (7,)


def test_open_scope_pins_the_connection(catalog: Catalog) -> None:
    """A transaction spanning several statements is never recycled mid-way."""
    catalog.connection.execute("BEGIN TRANSACTION")
    assert catalog._db.release_if_idle(0.0) is False
    catalog.connection.execute("COMMIT")
    assert catalog._db.release_if_idle(0.0) is True


def test_closed_catalog_refuses_further_statements(tmp_path: Path) -> None:
    """``close`` is final: the handle never reopens behind the caller's back."""
    cat = Catalog(tmp_path / "ws")
    cat.close()
    with pytest.raises(duckdb.Error):
        cat.connection.execute("SELECT 1")


def test_read_only_session_views_survive_a_release(tmp_path: Path) -> None:
    """TEMPORARY views of a read-only catalog are reinstalled on reopen."""
    workspace = tmp_path / "ws"
    Catalog(workspace).close()

    cat = Catalog(workspace, read_only=True)
    try:
        assert cat.connection.execute("SELECT COUNT(*) FROM v_simulation_summary").fetchone()
        assert cat._db.release_if_idle(0.0) is True
        assert cat.connection.execute("SELECT COUNT(*) FROM v_simulation_summary").fetchone()
    finally:
        cat.close()
