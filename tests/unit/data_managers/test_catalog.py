"""Tests for registry/catalog (DataCatalog with SQLAlchemy)."""

from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.data_managers.registry.catalog import DataCatalog


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
