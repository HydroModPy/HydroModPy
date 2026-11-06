"""The cache deletes the files it manages, and never a file the user provided.

The catalog stores a workspace-anchored path relative to the data folder. The
three delete paths (invalidate, subsume_entries, prune_older_than) resolved it
against the working directory, found nothing, and ``missing_ok`` hid it: no
cache file was ever deleted. Resolving it the catalog's way makes the delete
real, so it must also know what it may not touch.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.provenance.sidecars import sidecar_path_for
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def _catalog(workspace: Path) -> DataCatalogDuckDB:
    return DataCatalogDuckDB(workspace / "data" / "cache.duckdb")


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    return path


def _register(catalog: DataCatalogDuckDB, path: Path, *, is_custom: bool = False) -> None:
    catalog.register(
        variable="geology",
        source="custom" if is_custom else "brgm_1m",
        file_path=str(path),
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
        is_custom=is_custom,
    )


def test_invalidating_a_workspace_download_deletes_it_and_its_sidecar(tmp_path: Path) -> None:
    download = _write(tmp_path / "ws" / "data" / "geology" / "geology_brgm_1m_abc.gpkg")
    catalog = _catalog(tmp_path / "ws")
    try:
        _register(catalog, download)
        assert sidecar_path_for(download).is_file()
        catalog.invalidate(variable="geology", source="brgm_1m", delete_files=True)
    finally:
        catalog.close()
    assert not download.exists()
    assert not sidecar_path_for(download).exists()


def test_invalidating_a_user_file_forgets_it_and_leaves_it_on_disk(tmp_path: Path) -> None:
    user_file = _write(tmp_path / "ws" / "data" / "geology" / "geology_custom_mine.gpkg")
    catalog = _catalog(tmp_path / "ws")
    try:
        _register(catalog, user_file, is_custom=True)
        removed = catalog.invalidate(variable="geology", source="custom", delete_files=True)
    finally:
        catalog.close()
    assert removed == 1
    assert user_file.exists()


def test_invalidating_a_derived_copy_deletes_it(tmp_path: Path) -> None:
    copy = _write(tmp_path / "ws" / "data" / "blobs" / "geology" / "custom" / "mine_clip_1.gpkg")
    catalog = _catalog(tmp_path / "ws")
    try:
        _register(catalog, copy, is_custom=True)
        catalog.invalidate(variable="geology", source="custom", delete_files=True)
    finally:
        catalog.close()
    assert not copy.exists()
    assert not sidecar_path_for(copy).exists()


def test_pruning_deletes_old_downloads_and_spares_user_files(tmp_path: Path) -> None:
    download = _write(tmp_path / "ws" / "data" / "geology" / "geology_brgm_1m_old.gpkg")
    user_file = _write(tmp_path / "ws" / "data" / "geology" / "geology_custom_old.gpkg")
    catalog = _catalog(tmp_path / "ws")
    try:
        _register(catalog, download)
        _register(catalog, user_file, is_custom=True)
        removed = catalog.prune_older_than(days=-1, delete_files=True)
    finally:
        catalog.close()
    assert removed == 2
    assert not download.exists()
    assert user_file.exists()


def test_a_file_another_entry_still_names_is_kept(tmp_path: Path) -> None:
    shared = _write(tmp_path / "ws" / "data" / "geology" / "geology_brgm_1m_shared.gpkg")
    catalog = _catalog(tmp_path / "ws")
    try:
        _register(catalog, shared)
        catalog.register(
            variable="geology",
            source="brgm_50k",
            file_path=str(shared),
            bbox=(0.0, 0.0, 1.0, 1.0),
            crs="EPSG:2154",
        )
        removed = catalog.invalidate(variable="geology", source="brgm_1m", delete_files=True)
    finally:
        catalog.close()
    assert removed == 1
    assert shared.exists()
