"""The verbs of ``hmp data`` on the cache of a resolved workspace."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    Sidecar,
    load_sidecar,
    scan,
    write_sidecar,
)
from hydromodpy.data.request import cache_verbs


def _fetch(
    workspace: Path,
    variable: str,
    name: str,
    source: str,
    *,
    station_id: str | None = None,
    fetched_at: datetime | None = None,
) -> Path:
    """Write a file of the cache and its sidecar, as a run does."""
    data_root = workspace / "data"
    path = data_root / variable / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"{variable}/{name}".encode())
    CacheIndex(data_root).record(path, variable=variable, source=source, station_id=station_id)
    if fetched_at is not None:
        sidecar: Sidecar = load_sidecar(path)
        write_sidecar(path, sidecar.model_copy(update={"fetched_at": fetched_at}))
    return path


def _write_the_sidecar_of_a_user_file(path: Path) -> None:
    path.with_name(path.name + ".json").write_text(
        f'{{"source": "file", "sha256": "{sha256_of(path)}"}}', encoding="utf-8"
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    _fetch(root, "dem", "dem_ign_a.tif", "ign")
    _fetch(root, "dem", "dem_other_b.tif", "other")
    _fetch(root, "hydrometry", "hydrometry_hubeau_H1.csv", "hubeau", station_id="H1")
    _fetch(root, "hydrometry", "hydrometry_hubeau_H2.csv", "hubeau", station_id="H2")
    return root


def _names(workspace: Path) -> set[str]:
    return {row.path.name for row in scan(workspace / "data").rows}


@pytest.mark.parametrize(
    ("filters", "names"),
    [
        ({}, 4),
        ({"variable": "dem"}, 2),
        ({"provider": "hubeau"}, 2),
        ({"variable": "dem", "provider": "ign"}, 1),
        ({"variable": "dem", "provider": "hubeau"}, 0),
    ],
    ids=["all", "variable", "provider", "both", "none"],
)
def test_list_data_cache_filters_the_rows(workspace: Path, filters: dict, names: int) -> None:
    report = cache_verbs.list_data_cache(workspace, **filters)

    assert report is not None
    assert len(report.rows) == names


def test_list_data_cache_returns_none_without_a_data_folder(tmp_path: Path) -> None:
    assert cache_verbs.list_data_cache(tmp_path) is None


def test_list_data_cache_counts_the_user_files_it_does_not_list(workspace: Path) -> None:
    mine = workspace / "data" / "dem" / "mine.tif"
    mine.write_bytes(b"mine")
    _write_the_sidecar_of_a_user_file(mine)

    report = cache_verbs.list_data_cache(workspace)

    assert report is not None
    assert report.user_files == (mine.resolve(),)
    assert mine.name not in {row.path.name for row in report.rows}


def test_list_data_cache_refuses_the_database_of_2_0_0(workspace: Path) -> None:
    (workspace / "data" / FORMER_CACHE_DATABASE).write_bytes(b"duckdb")

    with pytest.raises(DataCacheError, match="hmp workspace clean --data-cache"):
        cache_verbs.list_data_cache(workspace)


@pytest.mark.parametrize(
    ("filters", "gone"),
    [
        ({"variable": "dem"}, {"dem_ign_a.tif", "dem_other_b.tif"}),
        ({"provider": "hubeau", "station_id": "H2"}, {"hydrometry_hubeau_H2.csv"}),
        ({"variable": "dem", "provider": "other"}, {"dem_other_b.tif"}),
    ],
    ids=["variable", "station", "variable and provider"],
)
def test_remove_data_entries_without_delete_files_keeps_the_files(
    workspace: Path, filters: dict, gone: set[str]
) -> None:
    before = _names(workspace)

    count = cache_verbs.remove_data_entries(workspace, **filters)

    assert count == len(gone)
    assert _names(workspace) == before - gone
    assert all(any((workspace / "data").rglob(name)) for name in gone)


def test_remove_data_entries_with_delete_files_removes_file_and_sidecar(workspace: Path) -> None:
    cache_verbs.remove_data_entries(workspace, variable="dem", provider="ign", delete_files=True)

    assert not list((workspace / "data").rglob("dem_ign_a.tif*"))
    assert (workspace / "data" / "dem" / "dem_other_b.tif").exists()


def test_a_dry_remove_counts_and_changes_nothing(workspace: Path) -> None:
    before = _names(workspace)

    assert cache_verbs.remove_data_entries(workspace, variable="dem", dry_run=True) == 2
    assert _names(workspace) == before


def test_remove_data_entries_without_a_data_folder_removes_nothing(tmp_path: Path) -> None:
    assert cache_verbs.remove_data_entries(tmp_path, variable="dem") == 0


def test_an_archive_restores_each_file_with_its_sidecar(workspace: Path, tmp_path: Path) -> None:
    archive = cache_verbs.archive_data_cache(
        tmp_path / "out" / "cache.tar.gz", workspace_root=workspace
    )
    elsewhere = tmp_path / "elsewhere"

    restored_into = cache_verbs.restore_data_cache(archive, workspace_root=elsewhere)

    assert restored_into == elsewhere / "data"
    original = {
        row.path.relative_to(workspace / "data"): row for row in scan(workspace / "data").rows
    }
    restored = {
        row.path.relative_to(elsewhere / "data"): row for row in scan(elsewhere / "data").rows
    }
    assert restored.keys() == original.keys()
    for key, row in restored.items():
        assert (row.sha256, row.variable, row.source, row.station_id) == (
            original[key].sha256,
            original[key].variable,
            original[key].source,
            original[key].station_id,
        )


def test_restore_data_cache_goes_where_it_is_told(workspace: Path, tmp_path: Path) -> None:
    archive = cache_verbs.archive_data_cache(tmp_path / "cache.tar", workspace_root=workspace)

    into = cache_verbs.restore_data_cache(
        archive, workspace_root=tmp_path / "unused", to=tmp_path / "chosen"
    )

    assert into == (tmp_path / "chosen").resolve()
    assert len(scan(into).rows) == 4


def test_an_archive_of_an_empty_cache_is_refused(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()

    with pytest.raises(FileNotFoundError, match="nothing to archive"):
        cache_verbs.archive_data_cache(tmp_path / "cache.tar", workspace_root=tmp_path)
