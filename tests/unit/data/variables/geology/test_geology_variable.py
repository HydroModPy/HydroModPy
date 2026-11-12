"""The geology variable: a download is a row of the data cache, and needs a data folder."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import box

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.variables.geology.variable import GeologyVariable

_MASK = (350_000, 6_780_000, 354_000, 6_784_000)


class _FakeBrgm:
    """A source that writes one GeoPackage into the folder it is given."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, request):
        self.calls += 1
        path = Path(request.out_dir) / "geology_brgm_1m_abc12345.gpkg"
        gpd.GeoDataFrame({"CODE": ["A"]}, geometry=[box(*_MASK)], crs="EPSG:2154").to_file(
            str(path), driver="GPKG"
        )
        return SimpleNamespace(files=[SimpleNamespace(path=path)])


def _config(tmp_path: Path, *, force_refresh: bool = False) -> SimpleNamespace:
    mask = tmp_path / "mask.gpkg"
    gpd.GeoDataFrame(geometry=[box(*_MASK)], crs="EPSG:2154").to_file(str(mask), driver="GPKG")
    return SimpleNamespace(source="brgm_1m", mask_path=mask, force_refresh=force_refresh)


def _variable(data_root: Path | None, folder: Path | None) -> GeologyVariable:
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)  # the store makes it before a variable runs
    return GeologyVariable(config=None, index=CacheIndex(data_root), data_dir=folder)


def test_a_download_is_a_row_and_the_second_call_is_served_from_it(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = _FakeBrgm()
    cfg = _config(tmp_path)

    first = _variable(data_root, data_root / "geology")._fetch_listed_source(source, cfg)
    second = _variable(data_root, data_root / "geology")._fetch_listed_source(source, cfg)

    assert source.calls == 1
    assert Path(first[0].data) == Path(second[0].data)
    (row,) = CacheIndex(data_root).rows(variable="geology", source="brgm_1m")
    assert row.path == Path(first[0].data).resolve()
    assert row.crs == "EPSG:2154"
    assert row.bbox == pytest.approx(_MASK)
    assert row.sha256 and row.bytes


def test_force_refresh_downloads_again(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = _FakeBrgm()

    _variable(data_root, data_root / "geology")._fetch_listed_source(source, _config(tmp_path))
    _variable(data_root, data_root / "geology")._fetch_listed_source(
        source, _config(tmp_path, force_refresh=True)
    )

    assert source.calls == 2


def test_a_download_without_a_data_folder_is_refused_and_leaves_the_user_cache_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "user-cache"))
    source = _FakeBrgm()

    with pytest.raises(ConfigError, match="no data folder"):
        _variable(None, None)._fetch_listed_source(source, _config(tmp_path))

    assert source.calls == 0
    assert not (tmp_path / "user-cache").exists()
