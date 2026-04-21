"""Tests for the extended 7-table InputCatalog schema."""

from __future__ import annotations

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def test_extended_tables_present():
    cat = DataCatalogDuckDB()
    names = set(cat.table_names())
    assert {"entries", "artifacts", "provenance", "stations",
            "coverage", "failures", "validation_reports"} <= names


def test_artifact_and_provenance_roundtrip():
    cat = DataCatalogDuckDB()
    aid = cat.write_artifact(
        artifact_type="dem", path="/tmp/x.tif",
        sha256="a" * 64, size_bytes=100, variable="dem",
    )
    assert aid >= 1
    cat.write_provenance(
        artifact_id=aid, variable="dem", source="ign",
        input_hash="a" * 64, tool_name="HTTPClient", tool_version="0.5",
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
    rows = cat.connection.execute(
        "SELECT lat, lon FROM stations WHERE station_id = 'A'"
    ).fetchall()
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
