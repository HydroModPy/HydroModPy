"""DataCatalog (DuckDB) registration tests for hydrography entries.

Covers register, find_cached lookup, upsert, list/invalidate, and on-disk
persistence.
"""

from __future__ import annotations

import pytest

# =====================================================================
# 11. Catalog / SQL registration
# =====================================================================


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
