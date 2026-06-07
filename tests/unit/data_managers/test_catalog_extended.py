"""Tests for the extended 7-table InputCatalog schema."""

from __future__ import annotations

from pathlib import Path

import duckdb

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.migrations import current_version


def test_extended_tables_present():
    cat = DataCatalogDuckDB()
    names = set(cat.table_names())
    assert {
        "_schema_version",
        "entries",
        "artifacts",
        "provenance",
        "stations",
        "coverage",
        "failures",
        "validation_reports",
    } <= names


def test_schema_version_table_records_data_cache_version():
    """The shared migrations runner records the ``data_cache`` component version."""
    cat = DataCatalogDuckDB()
    row = cat.connection.execute(
        "SELECT version FROM _schema_version WHERE component = 'data_cache'"
    ).fetchone()
    assert row == (1,)


def test_legacy_data_cache_schema_is_adopted(tmp_path: Path):
    """Old data caches already had V1 tables but no schema_migrations ledger."""

    db_path = tmp_path / "cache.duckdb"
    migration_sql = (
        Path(__file__).resolve().parents[3]
        / "hydromodpy"
        / "data"
        / "registry"
        / "migrations"
        / "0001_initial.sql"
    ).read_text(encoding="utf-8")
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(migration_sql)
        connection.execute(
            """
            CREATE TABLE _schema_version (
                component VARCHAR PRIMARY KEY,
                version VARCHAR NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO _schema_version (component, version) VALUES ('data_catalog', '1')"
        )
    finally:
        connection.close()

    with DataCatalogDuckDB(db_path) as catalog:
        assert current_version(catalog.connection) == 1
        row = catalog.connection.execute(
            "SELECT version FROM _schema_version WHERE component = 'data_cache'"
        ).fetchone()
        assert row == (1,)


def test_legacy_data_cache_schema_without_legacy_version_is_adopted(tmp_path: Path):
    """Some V1 caches have the tables but an empty migration ledger."""

    db_path = tmp_path / "cache.duckdb"
    migration_sql = (
        Path(__file__).resolve().parents[3]
        / "hydromodpy"
        / "data"
        / "registry"
        / "migrations"
        / "0001_initial.sql"
    ).read_text(encoding="utf-8")
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(migration_sql)
    finally:
        connection.close()

    with DataCatalogDuckDB(db_path) as catalog:
        assert current_version(catalog.connection) == 1


def test_artifact_and_provenance_roundtrip():
    cat = DataCatalogDuckDB()
    aid = cat.write_artifact(
        artifact_type="dem",
        path="/tmp/x.tif",
        sha256="a" * 64,
        size_bytes=100,
        variable="dem",
    )
    assert aid >= 1
    cat.write_provenance(
        artifact_id=aid,
        variable="dem",
        source="ign",
        input_hash="a" * 64,
        tool_name="HTTPClient",
        tool_version="0.5",
        parameters={"bbox": [0, 0, 1, 1]},
    )
    rows = cat.connection.execute(
        "SELECT artifact_id, input_hash FROM provenance WHERE artifact_id = ?",
        [aid],
    ).fetchall()
    assert rows and rows[0][1] == "a" * 64


def test_station_upsert():
    cat = DataCatalogDuckDB()
    cat.upsert_station(station_id="A", variable="piezometry", lat=48.0, lon=2.0)
    cat.upsert_station(station_id="A", variable="piezometry", lat=48.1, lon=2.1)
    rows = cat.connection.execute("SELECT lat, lon FROM stations WHERE station_id = 'A'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 48.1


def test_failure_and_validation_report():
    cat = DataCatalogDuckDB()
    cat.write_failure(variable="piezometry", error_type="NetworkError", message="boom")
    cat.write_validation_report(schema_name="TimeSeriesSchema", passed=False, errors=[{"k": 1}])
    fcount = cat.connection.execute("SELECT COUNT(*) FROM failures").fetchone()[0]
    vcount = cat.connection.execute("SELECT COUNT(*) FROM validation_reports").fetchone()[0]
    assert fcount == 1
    assert vcount == 1


def test_check_and_fix_drops_missing(tmp_path):
    cat = DataCatalogDuckDB()
    missing = tmp_path / "ghost.nc"
    cat.register(variable="dem", source="ign", file_path=missing)
    assert not missing.exists()
    summary = cat.check_and_fix()
    assert summary["dropped"] == 1
    assert cat.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
