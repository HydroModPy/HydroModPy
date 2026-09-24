"""A catalog path names the same file from any working directory.

The catalog stores paths relative to the workspace. A download registered by
its bare name was encoded against the cwd, so a run started inside
``projects/<name>/`` stored ``projects/<name>/<file>``. The managers then read
a stored path against ``data/<variable>/``, found nothing, forgot the entry and
fetched again. A sentinel took the same road and stopped being a sentinel.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.constants import SENTINEL_EMPTY


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace whose run starts inside one of its projects."""
    ws = tmp_path / "ws"
    project = ws / "projects" / "demo"
    project.mkdir(parents=True)
    monkeypatch.chdir(project)
    return ws


def _catalog(workspace: Path) -> DataCatalogDuckDB:
    return DataCatalogDuckDB(workspace / "data" / "cache.duckdb")


class _Stations(BaseVariableManager):
    VARIABLE_NAME = "hydrometry"

    def _fetch_from_source(self, source_cfg):
        raise AssertionError("the cache must answer")


class _Grids(BaseFieldManager):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg):
        raise AssertionError("the cache must answer")


def test_a_download_registered_by_name_is_stored_under_its_variable(workspace: Path) -> None:
    download = workspace / "data" / "hydrometry" / "hydrometry_hubeau_X1.csv"
    download.parent.mkdir(parents=True)
    download.write_text("datetime,value\n")
    with _catalog(workspace) as catalog:
        catalog.register(
            variable="hydrometry", source="hubeau", station_id="X1", file_path=download.name
        )
        entry = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="X1")

        assert entry.file_path == "data/hydrometry/hydrometry_hubeau_X1.csv"
        assert catalog.resolve_path(entry.file_path, variable="hydrometry") == download
        # A row an older version stored as a bare name still names its file.
        assert catalog.resolve_path(download.name, variable="hydrometry") == download


def test_a_sentinel_is_stored_as_written(workspace: Path) -> None:
    with _catalog(workspace) as catalog:
        catalog.register(
            variable="hydrometry", source="hubeau", station_id="X2", file_path=SENTINEL_EMPTY
        )
        entry = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="X2")

    assert entry.file_path == SENTINEL_EMPTY


def test_a_station_download_is_read_back_from_the_cache(workspace: Path) -> None:
    data = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3), "value": [1.0, 2.0, 3.0]}
    )
    record = PointRecord(
        station_id="X1",
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=data,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 3),
    )
    with _catalog(workspace) as catalog:
        manager = _Stations(
            config=None, catalog=catalog, data_dir=workspace / "data" / "hydrometry"
        )
        manager._persist_api_records([record], "hubeau")

        cached = manager._load_cached_api_record(source="hubeau", station_id="X1")

    assert cached is not None
    assert cached.data["value"].tolist() == [1.0, 2.0, 3.0]


def test_a_grid_download_is_read_back_from_the_cache(workspace: Path) -> None:
    bbox = (0.0, 0.0, 1.0, 1.0)
    grid = xr.Dataset(
        {"recharge": (("y", "x"), np.ones((2, 2)))}, coords={"y": [0, 1], "x": [0, 1]}
    )
    record = FieldRecord(
        variable="recharge",
        source="sim2",
        unit="mm/day",
        data=grid,
        bbox=bbox,
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
    )
    with _catalog(workspace) as catalog:
        manager = _Grids(
            config=None,
            catalog=catalog,
            data_dir=workspace / "data" / "recharge",
            project_period=(datetime(2020, 1, 1), datetime(2020, 12, 31)),
        )
        manager._persist_field_records([record], "sim2")

        cached = manager._find_cached_fields(source="sim2", variable_names=["recharge"], bbox=bbox)

    assert cached is not None
    assert float(cached[0].data["recharge"].sum()) == 4.0


def test_a_repair_keeps_an_entry_whose_file_exists(workspace: Path) -> None:
    kept = workspace / "data" / "hydrometry" / "kept.csv"
    gone = workspace / "data" / "hydrometry" / "gone.csv"
    kept.parent.mkdir(parents=True)
    kept.write_text("x")
    gone.write_text("x")
    with _catalog(workspace) as catalog:
        catalog.register(
            variable="hydrometry", source="hubeau", station_id="K", file_path=str(kept)
        )
        catalog.register(
            variable="hydrometry", source="hubeau", station_id="G", file_path=str(gone)
        )
        gone.unlink()

        summary = catalog.check_and_fix()
        left = set(catalog.list_entries(variable="hydrometry")["station_id"])

    assert summary["dropped"] == 1
    assert left == {"K"}


def test_a_cache_anchored_path_names_its_file(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "user-cache"
    monkeypatch.setenv("HMP_CACHE_HOME", str(cache_root))
    shared = cache_root / "shared" / "dem.tif"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"tif")
    with _catalog(workspace) as catalog:
        catalog.register(
            variable="dem", source="ign", file_path=str(shared), bbox=(0.0, 0.0, 1.0, 1.0)
        )
        (stored,) = catalog.list_entries(variable="dem")["file_path"]

        assert stored == "cache://shared/dem.tif"
        assert catalog.resolve_path(stored, variable="dem") == shared.resolve()


def test_a_river_network_download_is_read_back_from_the_cache(workspace: Path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString

    from hydromodpy.data.variables.hydrography.manager import HydrographyManager

    bbox = (0.0, 0.0, 1.0, 1.0)
    network = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326")
    with _catalog(workspace) as catalog:
        # The constructor starts a Whitebox backend the cache path never uses.
        manager = object.__new__(HydrographyManager)
        manager._catalog = catalog
        manager._data_dir = workspace / "data" / "hydrography"
        manager._persist_and_register(network, "bdtopage", bbox)

        cached = manager._try_load_cached("bdtopage", bbox)

    assert cached is not None
    assert len(cached) == 1
