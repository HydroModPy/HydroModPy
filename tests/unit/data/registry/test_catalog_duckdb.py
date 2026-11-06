"""The DuckDB data catalog: entries, lookups, the lifecycle and the layered cache."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.migrations.runner import current_version


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


def test_catalog_fresh_db_has_timestamptz_time_columns(tmp_path):
    """Fresh V1 caches always create ``date_start``/``date_end`` as TIMESTAMPTZ.

    The legacy ``VARCHAR`` -> ``TIMESTAMPTZ`` ALTER chain is gone in V1
    (clean-slate migration policy). Every new cache opens straight onto
    the canonical schema defined by ``0001_initial.sql``.
    """
    duckdb_path = tmp_path / "catalog.duckdb"
    with DataCatalogDuckDB(duckdb_path) as catalog:
        info = catalog.connection.execute("PRAGMA table_info('entries')").fetchall()
        types = {row[1]: row[2].upper() for row in info}

    assert types["date_start"] == "TIMESTAMP WITH TIME ZONE"
    assert types["date_end"] == "TIMESTAMP WITH TIME ZONE"


def test_a_product_version_reads_only_the_file_fetched_from_it(catalog, dummy_file):
    ask = {"variable": "dem", "source": "s"}
    catalog.register(file_path=dummy_file, fetch_metadata={}, **ask)
    assert catalog.find_cached(**ask) is not None
    assert catalog.find_cached(**ask, product_version="2") is None
    catalog.register(file_path=dummy_file, fetch_metadata={"product_version": "2"}, **ask)
    assert catalog.find_cached(**ask, product_version="2") is not None
    assert catalog.find_cached(**ask, product_version="3") is None


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


def _register_grid(
    catalog,
    tmp_path,
    *,
    variable="recharge",
    source="sim2",
    bbox=(100, 200, 300, 400),
    date_start="2020-01-01",
    date_end="2020-12-31",
    is_custom=False,
    filename="grid.nc",
):
    """Helper: register a grid entry with a real file on disk."""
    f = tmp_path / filename
    f.write_text("dummy")
    return catalog.register(
        variable=variable,
        source=source,
        file_path=f,
        bbox=bbox,
        date_start=date_start,
        date_end=date_end,
        is_custom=is_custom,
    )


@pytest.mark.fast
class TestSubsumeGridEntries:
    def test_smaller_bbox_inside_larger_is_subsumed(self, catalog, tmp_path):
        """Smaller bbox+dates fully inside larger bbox+dates -> deleted."""
        small_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(150, 250, 250, 350),
            date_start="2020-03-01",
            date_end="2020-09-30",
            filename="small.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 1
        # Only the large entry remains
        df = catalog.list_entries()
        assert len(df) == 1
        assert df.iloc[0]["id"] == large_id

    def test_entry_outside_bbox_not_subsumed(self, catalog, tmp_path):
        """Entry with bbox outside the new larger bbox -> kept."""
        outside_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(500, 600, 700, 800),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="outside.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 2

    def test_custom_entries_never_subsumed(self, catalog, tmp_path):
        """Entries with is_custom=1 are never deleted by subsume."""
        custom_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(150, 250, 250, 350),
            date_start="2020-03-01",
            date_end="2020-09-30",
            is_custom=True,
            filename="custom.nc",
        )
        large_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="large.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=large_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 2

    def test_exclude_id_prevents_self_deletion(self, catalog, tmp_path):
        """The newly registered entry (exclude_id) is never subsumed."""
        entry_id = _register_grid(
            catalog,
            tmp_path,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            filename="self.nc",
        )
        removed = catalog.subsume_entries(
            variable="recharge",
            source="sim2",
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-12-31",
            exclude_id=entry_id,
        )
        assert removed == 0
        assert len(catalog.list_entries()) == 1

    def test_upsert_different_files_no_collision(self, catalog, tmp_path):
        """Two grid files with station_id=NULL and different file_paths
        should coexist (not overwrite each other)."""
        f1 = tmp_path / "grid_a.nc"
        f1.write_text("a")
        f2 = tmp_path / "grid_b.nc"
        f2.write_text("b")

        id1 = catalog.register(
            variable="recharge",
            source="sim2",
            file_path=f1,
            bbox=(100, 200, 300, 400),
            date_start="2020-01-01",
            date_end="2020-06-30",
        )
        id2 = catalog.register(
            variable="recharge",
            source="sim2",
            file_path=f2,
            bbox=(100, 200, 300, 400),
            date_start="2020-07-01",
            date_end="2020-12-31",
        )
        assert id1 != id2
        assert len(catalog.list_entries()) == 2


@pytest.mark.fast
class TestCatalogHydrography:
    """Test that hydrography data can be registered in the DataCatalog."""

    def test_register_hydrography_entry(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)  # in-memory
        entry_id = cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/streams.shp",
            bbox=(-2.5, 47.5, -2.0, 48.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )
        assert entry_id > 0

    def test_find_cached_hydrography(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/streams.shp",
            bbox=(-3.0, 47.0, -1.0, 49.0),
            crs="EPSG:4326",
            is_custom=False,
            file_mtime=0.0,
        )

        # find_cached should find entries for a smaller bbox
        result = cat.find_cached(
            variable="hydrography",
            source="bdtopage",
            bbox=(-2.5, 47.5, -2.0, 48.0),
        )
        assert result is not None

    def test_upsert_same_key(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        id1 = cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/streams_v1.shp",
            file_mtime=0.0,
        )
        id2 = cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/streams_v1.shp",
            file_mtime=1.0,
        )
        # Upsert: same entry updated, not duplicated
        assert id1 == id2

    def test_list_entries(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="custom",
            file_path="/tmp/a.shp",
            is_custom=True,
            file_mtime=0.0,
        )
        cat.register(
            variable="hydrography",
            source="bdtopage",
            file_path="/tmp/b.shp",
            file_mtime=0.0,
        )
        df = cat.list_entries(variable="hydrography")
        assert len(df) == 2

    def test_invalidate_entry(self):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        cat = DataCatalog(db_path=None)
        cat.register(
            variable="hydrography",
            source="osm",
            file_path="/tmp/osm.shp",
            file_mtime=0.0,
        )
        cat.invalidate(variable="hydrography", source="osm")
        df = cat.list_entries(variable="hydrography")
        assert len(df) == 0

    def test_duckdb_persistence(self, tmp_path):
        from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog

        db = tmp_path / "catalog.duckdb"
        cat1 = DataCatalog(db_path=db)
        cat1.register(
            variable="hydrography",
            source="euhydro",
            file_path="/tmp/eu.shp",
            file_mtime=0.0,
        )

        # Reopen from disk
        cat2 = DataCatalog(db_path=db)
        df = cat2.list_entries(variable="hydrography")
        assert len(df) == 1
        assert df.iloc[0]["source"] == "euhydro"
