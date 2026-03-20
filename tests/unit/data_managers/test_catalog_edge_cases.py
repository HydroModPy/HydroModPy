"""Edge-case tests for registry/catalog (DataCatalog with SQLAlchemy)."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from hydromodpy.data_managers.registry.catalog import DataCatalog

pytestmark = pytest.mark.fast


@pytest.fixture
def catalog():
    """In-memory catalog for testing."""
    return DataCatalog(None)


class TestCatalogEdgeCases:
    """Cover edge cases and less-obvious behaviour of DataCatalog."""

    # ------------------------------------------------------------------
    # 1. find_cached() with inverted bbox
    # ------------------------------------------------------------------
    def test_find_cached_inverted_bbox_returns_none(self, catalog, tmp_path):
        """An inverted bbox (xmin > xmax) must return None, not crash."""
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
            bbox=(3.0, 46.0, 0.0, 43.0),  # inverted
        )
        assert result is None

    # ------------------------------------------------------------------
    # 2. find_cached() with None dates
    # ------------------------------------------------------------------
    def test_find_cached_none_dates_matches_any(self, catalog, tmp_path):
        """When date_start/date_end are None, temporal filtering is skipped."""
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

    # ------------------------------------------------------------------
    # 3. find_cached() ordering — newest (highest id) wins
    # ------------------------------------------------------------------
    def test_find_cached_returns_newest_entry(self, catalog, tmp_path):
        """When two entries match, find_cached returns the one with highest id."""
        f1 = tmp_path / "old.csv"
        f1.write_text("old")
        f2 = tmp_path / "new.csv"
        f2.write_text("new")

        id1 = catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=f1,
            station_id="ST001",
            date_start=datetime(2019, 1, 1),
            date_end=datetime(2025, 12, 31),
        )
        id2 = catalog.register(
            variable="hydrometry",
            source="hubeau",
            file_path=f2,
            station_id="ST001",
            date_start=datetime(2018, 1, 1),
            date_end=datetime(2026, 12, 31),
        )
        # Upsert means same (variable, source, station_id) → updated in-place,
        # so only one entry survives. Verify it carries the newer dates.
        entry = catalog.find_cached(
            variable="hydrometry",
            source="hubeau",
            station_id="ST001",
        )
        assert entry is not None
        assert entry.date_start == "2018-01-01T00:00:00"

        # Now test with *different* station_ids so two entries coexist.
        id_a = catalog.register(
            variable="piezometry",
            source="hubeau",
            file_path=f1,
            station_id="A",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2025, 12, 31),
        )
        id_b = catalog.register(
            variable="piezometry",
            source="hubeau",
            file_path=f2,
            station_id="B",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2025, 12, 31),
        )
        # Query without station_id filter — both match, newest id should win.
        entry = catalog.find_cached(
            variable="piezometry",
            source="hubeau",
        )
        assert entry is not None
        assert entry.id == max(id_a, id_b)

    # ------------------------------------------------------------------
    # 4. register() with non-existent file
    # ------------------------------------------------------------------
    def test_register_nonexistent_file_does_not_crash(self, catalog):
        """Registering a file that doesn't exist should succeed; mtime is None."""
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

    # ------------------------------------------------------------------
    # 5. register() upsert — same key updates, not duplicates
    # ------------------------------------------------------------------
    def test_register_upsert_updates_not_duplicates(self, catalog, tmp_path):
        """Re-registering same (variable, source, station_id) updates the entry."""
        f = tmp_path / "data.csv"
        f.write_text("v1")

        catalog.register(
            variable="etp",
            source="sim2",
            file_path=f,
            station_id="GRID01",
            unit="mm/d",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 6, 30),
        )
        catalog.register(
            variable="etp",
            source="sim2",
            file_path=f,
            station_id="GRID01",
            unit="m/s",
            date_start=datetime(2019, 1, 1),
            date_end=datetime(2023, 12, 31),
        )

        df = catalog.list_entries(variable="etp")
        assert len(df) == 1, "Upsert should not create a duplicate entry"
        assert df.iloc[0]["date_start"] == "2019-01-01T00:00:00"

        entry = catalog.find_cached(
            variable="etp", source="sim2", station_id="GRID01"
        )
        assert entry.unit == "m/s"

    # ------------------------------------------------------------------
    # 6. subsume_entries() with equal bbox
    # ------------------------------------------------------------------
    def test_subsume_equal_bbox_removes_entry(self, catalog, tmp_path):
        """An entry with the *same* bbox as the new one should be subsumed."""
        f_old = tmp_path / "old_grid.nc"
        f_old.write_text("old")
        f_new = tmp_path / "new_grid.nc"
        f_new.write_text("new")

        id_a = catalog.register(
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
            bbox=(0.0, 43.0, 3.0, 46.0),  # same bbox
            date_start="2020-01-01",
            date_end="2020-12-31",
        )

        removed = catalog.subsume_entries(
            variable="precipitation",
            source="sim2",
            bbox=(0.0, 43.0, 3.0, 46.0),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=id_b,  # protect the new entry
        )
        assert removed == 1

        df = catalog.list_entries(variable="precipitation")
        assert len(df) == 1
        assert df.iloc[0]["id"] == id_b

    # ------------------------------------------------------------------
    # 7. subsume_entries() with exclude_id
    # ------------------------------------------------------------------
    def test_subsume_exclude_id_not_deleted(self, catalog, tmp_path):
        """The entry specified by exclude_id must NOT be deleted."""
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

        df = catalog.list_entries(variable="recharge")
        assert len(df) == 1
        assert df.iloc[0]["id"] == entry_id

    # ------------------------------------------------------------------
    # 8. cleanup() with sentinel entries (custom / empty)
    # ------------------------------------------------------------------
    def test_cleanup_preserves_sentinel_entries(self, catalog):
        """Entries with file_path='custom' or 'empty' must survive cleanup."""
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

        removed = catalog.cleanup()
        assert removed == 0

        df = catalog.list_entries()
        assert len(df) == 2

    # ------------------------------------------------------------------
    # 9. cleanup() with missing file
    # ------------------------------------------------------------------
    def test_cleanup_removes_missing_file_entry(self, catalog, tmp_path):
        """An entry whose file no longer exists should be removed by cleanup."""
        gone = tmp_path / "vanished.nc"
        gone.write_text("temp")
        catalog.register(
            variable="temperature",
            source="sim2",
            file_path=gone,
            station_id="TMP01",
        )
        gone.unlink()

        removed = catalog.cleanup()
        assert removed == 1
        assert len(catalog.list_entries()) == 0

    # ------------------------------------------------------------------
    # 10. list_entries() pagination (limit / offset)
    # ------------------------------------------------------------------
    def test_list_entries_pagination(self, catalog, tmp_path):
        """Register 5 entries, verify limit and offset work correctly."""
        for i in range(5):
            f = tmp_path / f"file_{i}.csv"
            f.write_text(f"data{i}")
            catalog.register(
                variable="hydrometry",
                source="hubeau",
                file_path=f,
                station_id=f"ST{i:03d}",
            )

        df_all = catalog.list_entries()
        assert len(df_all) == 5

        df_limit = catalog.list_entries(limit=2)
        assert len(df_limit) == 2

        df_offset = catalog.list_entries(offset=3)
        assert len(df_offset) == 2

        df_both = catalog.list_entries(limit=2, offset=1)
        assert len(df_both) == 2

    # ------------------------------------------------------------------
    # 11. invalidate() with delete_files=True
    # ------------------------------------------------------------------
    def test_invalidate_delete_files_removes_file(self, catalog, tmp_path):
        """invalidate(delete_files=True) should unlink the physical file."""
        real_file = tmp_path / "to_remove.parquet"
        real_file.write_text("important data")
        assert real_file.exists()

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

    # ------------------------------------------------------------------
    # 12. Schema migration on fresh DB
    # ------------------------------------------------------------------
    def test_fresh_db_creates_tables_and_sets_schema_version(self):
        """A fresh in-memory DataCatalog should have tables and schema_version=2."""
        cat = DataCatalog(None)

        with cat.engine.connect() as conn:
            row = conn.execute(text("SELECT version FROM _schema_meta")).fetchone()
            assert row is not None
            assert row[0] == 2

        # Verify the entries table exists and is usable.
        entry_id = cat.register(
            variable="test",
            source="unit",
            file_path="dummy",
            station_id="X",
        )
        assert entry_id > 0
