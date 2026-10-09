"""A frozen run refuses a request the cache covers only in part, before the download.

The missing days used to be fetched, merged into the cached chronicle and written
under a new name, which deleted the file the lockfile pins. The refusal came after,
when the new file was registered.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.provenance.lockfile import set_frozen_mode
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


class _Manager(BaseVariableManager):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"

    def _fetch_from_source(self, source_cfg):
        return []


def _record(station: str, start: str, end: str) -> PointRecord:
    dates = pd.date_range(start, end, freq="D")
    return PointRecord(
        station_id=station,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": range(len(dates))}),
        date_start=datetime.fromisoformat(start),
        date_end=datetime.fromisoformat(end),
    )


@pytest.fixture
def frozen_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    """A workspace with one cached chronicle, its lockfile, and frozen mode on."""
    from hydromodpy.cli.commands.run import _post_run_lockfile_write

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "demo"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    project.mkdir(parents=True)
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    manager = _Manager(
        config=SimpleNamespace(),
        catalog=catalog,
        project_period=(datetime(2000, 1, 1), datetime(2000, 1, 31)),
        data_dir=data_dir,
    )
    manager._persist_api_records([_record("A", "2000-01-01", "2000-01-31")], "hubeau")
    catalog.close()
    config_path = project / "project.toml"
    config_path.write_text("# placeholder\n")
    _post_run_lockfile_write(config_path, {"workspace": {"project_root": str(project)}})
    set_frozen_mode(True, project_root=project)
    try:
        yield workspace, data_dir
    finally:
        set_frozen_mode(False)


def _manager(workspace: Path, data_dir: Path, period: tuple[datetime, datetime]) -> _Manager:
    return _Manager(
        config=SimpleNamespace(),
        catalog=DataCatalogDuckDB(workspace / "data" / "cache.duckdb"),
        project_period=period,
        data_dir=data_dir,
    )


def _no_download(*_args):
    raise AssertionError("a frozen run reached the network")


@pytest.mark.fast
def test_a_longer_period_is_refused_before_the_download(
    frozen_project: tuple[Path, Path],
) -> None:
    workspace, data_dir = frozen_project
    before = sorted(p.name for p in data_dir.iterdir())
    manager = _manager(workspace, data_dir, (datetime(2000, 1, 1), datetime(2000, 2, 28)))
    cfg = SimpleNamespace(station_ids=["A"], force_refresh=False)

    with pytest.raises(DataCacheError, match="Frozen data mode forbids a download") as info:
        manager._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")

    assert "cached from 2000-01-01 to 2000-01-31" in str(info.value)
    assert "asks for 2000-01-01 to 2000-02-28" in str(info.value)
    assert sorted(p.name for p in data_dir.iterdir()) == before


@pytest.mark.fast
def test_a_search_by_extent_is_refused_before_the_download(
    frozen_project: tuple[Path, Path],
) -> None:
    workspace, data_dir = frozen_project
    manager = _manager(workspace, data_dir, (datetime(2000, 1, 1), datetime(2000, 1, 31)))
    cfg = SimpleNamespace(station_ids=[], force_refresh=False)

    with pytest.raises(DataCacheError, match="asked for by extent or with force_refresh"):
        manager._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")


@pytest.mark.fast
def test_a_covered_period_is_served_from_the_cache(frozen_project: tuple[Path, Path]) -> None:
    workspace, data_dir = frozen_project
    manager = _manager(workspace, data_dir, (datetime(2000, 1, 5), datetime(2000, 1, 20)))
    cfg = SimpleNamespace(station_ids=["A"], force_refresh=False, mask_path=None)

    records = manager._fetch_with_station_cache(cfg, _no_download, source_name="hubeau")

    assert [r.station_id for r in records] == ["A"]
