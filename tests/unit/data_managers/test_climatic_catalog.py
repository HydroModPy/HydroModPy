"""Tests for DataCatalog subsumption of climatic grid entries."""

from __future__ import annotations

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB as DataCatalog


@pytest.fixture
def catalog():
    """In-memory catalog for testing."""
    return DataCatalog(None)


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
class TestSubsumeEntries:
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
