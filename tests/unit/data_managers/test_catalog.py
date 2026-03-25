"""Tests for registry/catalog (DataCatalog with SQLAlchemy)."""

from datetime import datetime
from pathlib import Path
import sqlite3

import pytest

from hydromodpy.data.registry.catalog import DataCatalog


@pytest.fixture
def catalog():
    """In-memory catalog for testing."""
    return DataCatalog(None)


@pytest.fixture
def dummy_file(tmp_path):
    """Create a dummy file to register."""
    f = tmp_path / "test.parquet"
    f.write_text("dummy")
    return f


class TestCatalogRegister:
    def test_register_returns_id(self, catalog, dummy_file):
        entry_id = catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="J7214001",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 12, 31),
        )
        assert isinstance(entry_id, int)
        assert entry_id > 0

    def test_list_entries(self, catalog, dummy_file):
        catalog.register(variable="hydrometry", source="hubeau", file_path=dummy_file)
        catalog.register(variable="piezometry", source="custom", file_path=dummy_file)

        df = catalog.list_entries()
        assert len(df) == 2

        df_hydro = catalog.list_entries(variable="hydrometry")
        assert len(df_hydro) == 1

    def test_source_unit_roundtrip(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry",
            source="custom",
            file_path=dummy_file,
            station_id="ST001",
            unit="m3/s",
            source_unit="L/s",
        )

        entry = catalog.find_cached(
            variable="hydrometry", source="custom", station_id="ST001"
        )
        assert entry is not None
        assert entry.unit == "m3/s"
        assert entry.source_unit == "L/s"

        df = catalog.list_entries(variable="hydrometry")
        assert df.iloc[0]["source_unit"] == "L/s"


class TestCatalogFindCached:
    def test_find_by_station(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 12, 31),
        )
        entry = catalog.find_cached(
            variable="hydrometry", source="hubeau", station_id="ST001"
        )
        assert entry is not None
        assert entry.station_id == "ST001"

    def test_not_found(self, catalog):
        entry = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="NOPE")
        assert entry is None

    def test_superset_period(self, catalog, dummy_file):
        # Cache covers 2019-2025
        catalog.register(
            variable="hydrometry", source="hubeau", file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2019, 1, 1), date_end=datetime(2025, 12, 31),
        )
        # Query for 2020-2023 → should find it (superset)
        entry = catalog.find_cached(
            variable="hydrometry", source="hubeau", station_id="ST001",
            date_start=datetime(2020, 1, 1), date_end=datetime(2023, 12, 31),
        )
        assert entry is not None


class TestCatalogUpsert:
    def test_register_twice_no_duplicate(self, catalog, dummy_file):
        """Re-registering same (variable, source, station_id) updates, not duplicates."""
        catalog.register(
            variable="hydrometry", source="hubeau", file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2020, 1, 1), date_end=datetime(2020, 12, 31),
        )
        catalog.register(
            variable="hydrometry", source="hubeau", file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2019, 1, 1), date_end=datetime(2023, 12, 31),
        )
        df = catalog.list_entries()
        assert len(df) == 1
        assert df.iloc[0]["date_start"] == "2019-01-01T00:00:00"

    def test_different_stations_separate_entries(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry", source="hubeau", file_path=dummy_file,
            station_id="ST001",
        )
        catalog.register(
            variable="hydrometry", source="hubeau", file_path=dummy_file,
            station_id="ST002",
        )
        assert len(catalog.list_entries()) == 2


class TestCatalogCleanup:
    def test_cleanup_removes_stale_entries(self, catalog, tmp_path):
        existing = tmp_path / "exists.csv"
        existing.write_text("ok")
        gone = tmp_path / "gone.csv"
        gone.write_text("ok")
        catalog.register(variable="hydrometry", source="hubeau",
                         file_path=existing, station_id="A")
        catalog.register(variable="hydrometry", source="hubeau",
                         file_path=gone, station_id="B")

        gone.unlink()  # simulate manual deletion

        removed = catalog.cleanup()
        assert removed == 1
        assert len(catalog.list_entries()) == 1

    def test_cleanup_skips_custom_sentinel(self, catalog):
        catalog.register(variable="hydrometry", source="custom",
                         file_path="custom", station_id="C", is_custom=True)
        removed = catalog.cleanup()
        assert removed == 0
        assert len(catalog.list_entries()) == 1


class TestCatalogInvalidate:
    def test_invalidate_by_variable(self, catalog, dummy_file):
        catalog.register(variable="hydrometry", source="hubeau", file_path=dummy_file)
        catalog.register(variable="piezometry", source="hubeau", file_path=dummy_file)

        count = catalog.invalidate(variable="hydrometry")
        assert count == 1
        assert len(catalog.list_entries()) == 1

    def test_invalidate_with_file_deletion(self, catalog, tmp_path):
        f = tmp_path / "to_delete.parquet"
        f.write_text("data")
        catalog.register(variable="hydrometry", source="test", file_path=f)

        catalog.invalidate(variable="hydrometry", delete_files=True)
        assert not f.exists()


class TestCatalogMigrations:
    def test_adds_source_unit_column_to_legacy_entries_table(self, tmp_path):
        db_path = tmp_path / "legacy_catalog.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variable VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    station_id VARCHAR NULL,
                    bbox_xmin FLOAT NULL,
                    bbox_ymin FLOAT NULL,
                    bbox_xmax FLOAT NULL,
                    bbox_ymax FLOAT NULL,
                    crs VARCHAR NULL,
                    date_start VARCHAR NULL,
                    date_end VARCHAR NULL,
                    frequency VARCHAR NULL,
                    unit VARCHAR NULL,
                    file_path TEXT NOT NULL,
                    file_mtime FLOAT NULL,
                    created_at DATETIME NULL,
                    is_custom INTEGER DEFAULT 0
                )
                """
            )
            conn.commit()

        catalog = DataCatalog(db_path)
        dummy_file = tmp_path / "legacy.csv"
        dummy_file.write_text("dummy")

        catalog.register(
            variable="hydrometry",
            source="custom",
            file_path=dummy_file,
            station_id="LEGACY01",
            unit="m3/s",
            source_unit="L/s",
        )

        entry = catalog.find_cached(
            variable="hydrometry", source="custom", station_id="LEGACY01"
        )
        assert entry is not None
        assert entry.source_unit == "L/s"
