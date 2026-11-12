"""The geology variable fetches a BRGM map once and records it as a row of the data cache.

The map is a GeoPackage in Lambert-93 meters. A download needs a data folder.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import box

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.variables.geology.variable import GeologyVariable

MASK = (350_000, 6_780_000, 354_000, 6_784_000)


class FakeBrgm:
    """A source that writes one GeoPackage into the folder it is given."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, request):
        self.calls += 1
        path = Path(request.out_dir) / "geology_brgm_1m_abc12345.gpkg"
        gpd.GeoDataFrame({"CODE": ["A"]}, geometry=[box(*MASK)], crs="EPSG:2154").to_file(
            str(path), driver="GPKG"
        )
        return SimpleNamespace(files=[SimpleNamespace(path=path)])


def config(tmp_path: Path, *, force_refresh: bool = False) -> SimpleNamespace:
    mask = tmp_path / "mask.gpkg"
    gpd.GeoDataFrame(geometry=[box(*MASK)], crs="EPSG:2154").to_file(str(mask), driver="GPKG")
    return SimpleNamespace(source="brgm_1m", mask_path=mask, force_refresh=force_refresh)


def variable(data_root: Path | None, folder: Path | None) -> GeologyVariable:
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)  # the store makes it before a variable runs
    return GeologyVariable(config=None, index=CacheIndex(data_root), data_dir=folder)


def test_a_second_call_is_served_from_the_cache(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = FakeBrgm()
    cfg = config(tmp_path)

    first = variable(data_root, data_root / "geology")._fetch_listed_source(source, cfg)
    second = variable(data_root, data_root / "geology")._fetch_listed_source(source, cfg)

    assert source.calls == 1
    assert Path(first[0].data) == Path(second[0].data)
    (row,) = CacheIndex(data_root).rows(variable="geology", source="brgm_1m")
    assert row.path == Path(first[0].data).resolve()
    assert row.crs == "EPSG:2154"
    assert row.bbox == pytest.approx(MASK)
    assert row.sha256 and row.bytes


def test_force_refresh_downloads_again(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = FakeBrgm()

    variable(data_root, data_root / "geology")._fetch_listed_source(source, config(tmp_path))
    variable(data_root, data_root / "geology")._fetch_listed_source(
        source, config(tmp_path, force_refresh=True)
    )

    assert source.calls == 2


def test_no_data_folder_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "user-cache"))
    source = FakeBrgm()

    with pytest.raises(ConfigError, match="no data folder"):
        variable(None, None)._fetch_listed_source(source, config(tmp_path))

    assert source.calls == 0
    assert not (tmp_path / "user-cache").exists()
