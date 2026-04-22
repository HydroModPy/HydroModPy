"""Tests for registry/catalog_duckdb (DataCatalogDuckDB — mirror of test_catalog.py)."""

from datetime import datetime
from pathlib import Path
import sqlite3

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


@pytest.fixture
def catalog():
    return DataCatalogDuckDB(None)


@pytest.fixture
def dummy_file(tmp_path):
    f = tmp_path / "test.parquet"
    f.write_text("dummy")
    return f


class TestRegister:
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
            variable="hydrometry",
            source="custom",
            station_id="ST001",
        )
        assert entry is not None
        assert entry.unit == "m3/s"
        assert entry.source_unit == "L/s"

        df = catalog.list_entries(variable="hydrometry")
        assert df.iloc[0]["source_unit"] == "L/s"


class TestFindCached:
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
            variable="hydrometry",
            source="hubeau",
            station_id="ST001",
        )
        assert entry is not None
        assert entry.station_id == "ST001"

    def test_not_found(self, catalog):
        entry = catalog.find_cached(
            variable="hydrometry",
            source="hubeau",
            station_id="NOPE",
        )
        assert entry is None

    def test_superset_period(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2019, 1, 1),
            date_end=datetime(2025, 12, 31),
        )
        entry = catalog.find_cached(
            variable="hydrometry",
            source="hubeau",
            station_id="ST001",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2023, 12, 31),
        )
        assert entry is not None

    def test_superset_bbox(self, catalog, dummy_file):
        catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=dummy_file,
            bbox=(0.0, 42.0, 5.0, 48.0),
        )
        entry = catalog.find_cached(
            variable="precipitation",
            source="sim2",
            bbox=(1.0, 43.0, 4.0, 47.0),
        )
        assert entry is not None


class TestUpsert:
    def test_register_twice_no_duplicate(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 12, 31),
        )
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST001",
            date_start=datetime(2019, 1, 1),
            date_end=datetime(2023, 12, 31),
        )
        df = catalog.list_entries()
        assert len(df) == 1
        assert df.iloc[0]["date_start"] == "2019-01-01T00:00:00"

    def test_different_stations_separate_entries(self, catalog, dummy_file):
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST001",
        )
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=dummy_file,
            station_id="ST002",
        )
        assert len(catalog.list_entries()) == 2


class TestCleanup:
    def test_cleanup_removes_stale_entries(self, catalog, tmp_path):
        existing = tmp_path / "exists.csv"
        existing.write_text("ok")
        gone = tmp_path / "gone.csv"
        gone.write_text("ok")
        catalog.register(variable="hydrometry", source="hubeau", file_path=existing, station_id="A")
        catalog.register(variable="hydrometry", source="hubeau", file_path=gone, station_id="B")

        gone.unlink()
        removed = catalog.cleanup()
        assert removed == 1
        assert len(catalog.list_entries()) == 1

    def test_cleanup_skips_custom_sentinel(self, catalog):
        catalog.register(
            variable="hydrometry",
            source="custom",
            file_path="custom",
            station_id="C",
            is_custom=True,
        )
        removed = catalog.cleanup()
        assert removed == 0
        assert len(catalog.list_entries()) == 1


class TestInvalidate:
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


class TestSubsumeEntries:
    def test_subsume_smaller_grid(self, catalog, tmp_path):
        small = tmp_path / "small.nc"
        small.write_text("small grid")
        big = tmp_path / "big.nc"
        big.write_text("big grid")

        catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=small,
            bbox=(1.0, 43.0, 3.0, 46.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        big_id = catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=big,
            bbox=(0.0, 42.0, 5.0, 48.0),
            date_start="2019-01-01",
            date_end="2025-12-31",
        )

        removed = catalog.subsume_entries(
            variable="precipitation",
            source="sim2",
            bbox=(0.0, 42.0, 5.0, 48.0),
            date_start="2019-01-01",
            date_end="2025-12-31",
            exclude_id=big_id,
        )
        assert removed == 1
        assert not small.exists()
        assert len(catalog.list_entries()) == 1


class TestEdgeCases:
    def test_find_cached_inverted_bbox_returns_none(self, catalog, tmp_path):
        f = tmp_path / "grid.nc"
        f.write_text("data")
        catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=f,
            bbox=(0.0, 43.0, 3.0, 46.0),
        )
        result = catalog.find_cached(
            variable="precipitation",
            source="sim2",
            bbox=(3.0, 46.0, 0.0, 43.0),
        )
        assert result is None

    def test_find_cached_none_dates_matches_any(self, catalog, tmp_path):
        f = tmp_path / "station.csv"
        f.write_text("data")
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=f,
            station_id="ST001",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2024, 12, 31),
        )
        entry = catalog.find_cached(
            variable="hydrometry",
            source="hubeau",
            station_id="ST001",
            date_start=None,
            date_end=None,
        )
        assert entry is not None
        assert entry.station_id == "ST001"

    def test_register_nonexistent_file_does_not_crash(self, catalog):
        entry_id = catalog.register(
            variable="precipitation",
            source="sim2",
            file_path="/nonexistent/path/to/data.nc",
            station_id="GHOST",
        )
        assert entry_id > 0
        entry = catalog.find_cached(
            variable="precipitation",
            source="sim2",
            station_id="GHOST",
        )
        assert entry is not None
        assert entry.file_mtime is None

    def test_subsume_equal_bbox_removes_entry(self, catalog, tmp_path):
        f_old = tmp_path / "old_grid.nc"
        f_old.write_text("old")
        f_new = tmp_path / "new_grid.nc"
        f_new.write_text("new")

        catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=f_old,
            bbox=(0.0, 43.0, 3.0, 46.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        id_b = catalog.register(
            variable="precipitation",
            source="sim2",
            file_path=f_new,
            bbox=(0.0, 43.0, 3.0, 46.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        removed = catalog.subsume_entries(
            variable="precipitation",
            source="sim2",
            bbox=(0.0, 43.0, 3.0, 46.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=id_b,
        )
        assert removed == 1
        df = catalog.list_entries(variable="precipitation")
        assert len(df) == 1

    def test_subsume_exclude_id_not_deleted(self, catalog, tmp_path):
        f = tmp_path / "grid.nc"
        f.write_text("data")
        entry_id = catalog.register(
            variable="recharge",
            source="sim2",
            file_path=f,
            bbox=(1.0, 44.0, 2.0, 45.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(0.0, 43.0, 3.0, 46.0),
            date_start="2019-01-01",
            date_end="2021-12-31",
            exclude_id=entry_id,
        )
        assert removed == 0
        assert len(catalog.list_entries(variable="recharge")) == 1

    def test_list_entries_pagination(self, catalog, tmp_path):
        for i in range(5):
            f = tmp_path / f"file_{i}.csv"
            f.write_text(f"data{i}")
            catalog.register(
                variable="hydrometry",
                source="hubeau",
                file_path=f,
                station_id=f"ST{i:03d}",
            )
        assert len(catalog.list_entries()) == 5
        assert len(catalog.list_entries(limit=2)) == 2
        assert len(catalog.list_entries(offset=3)) == 2
        assert len(catalog.list_entries(limit=2, offset=1)) == 2

    def test_invalidate_delete_files_removes_file(self, catalog, tmp_path):
        real_file = tmp_path / "to_remove.parquet"
        real_file.write_text("important data")
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=real_file,
            station_id="DEL01",
        )
        count = catalog.invalidate(
            variable="hydrometry",
            source="hubeau",
            station_id="DEL01",
            delete_files=True,
        )
        assert count == 1
        assert not real_file.exists()
        assert len(catalog.list_entries()) == 0

    def test_cleanup_preserves_sentinel_entries(self, catalog):
        catalog.register(
            variable="hydrometry",
            source="custom",
            file_path="custom",
            station_id="CUSTOM01",
            is_custom=True,
        )
        catalog.register(
            variable="piezometry",
            source="custom",
            file_path="empty",
            station_id="EMPTY01",
            is_custom=True,
        )
        assert catalog.cleanup() == 0
        assert len(catalog.list_entries()) == 2


class TestContextManager:
    def test_context_manager(self, tmp_path):
        duckdb_path = tmp_path / "catalog.duckdb"
        with DataCatalogDuckDB(duckdb_path) as cat:
            cat.register(variable="test", source="src", file_path="/tmp/test.csv")
            assert len(cat.list_entries()) == 1
