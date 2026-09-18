"""Fill the stream burn network from ``[[data.hydrography.sources]]``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.data.variables.hydrography.resolver import (
    resolve_stream_geometry_path_from_data_sources,
)

_NETWORK = LineString([(350000.0, 6800000.0), (350000.0, 6805000.0)])


def _write_network(path: Path) -> Path:
    gpd.GeoDataFrame({"id": [1]}, geometry=[_NETWORK], crs="EPSG:2154").to_file(path)
    return path


def _write_raster(path: Path) -> Path:
    profile = {
        "driver": "GTiff",
        "height": 4,
        "width": 4,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(340000.0, 6810000.0, 1000.0, 1000.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.zeros((4, 4), dtype="float32"), 1)
    return path


def _cfg(
    sources: list,
    *,
    x_outlet: float | None = 350000.0,
    y_outlet: float | None = 6802000.0,
    dem_init_path: Path | None = None,
):
    return SimpleNamespace(
        data=SimpleNamespace(hydrography=SimpleNamespace(sources=sources)),
        geographic=SimpleNamespace(
            x_outlet=x_outlet,
            y_outlet=y_outlet,
            crs_project="EPSG:2154",
            dem_init_path=dem_init_path,
        ),
    )


def _custom(path):
    return SimpleNamespace(source="custom", path=path, force_refresh=False)


def test_a_relative_custom_path_anchors_on_the_toml_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _write_network(project / "network.gpkg")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom("network.gpkg")]),
        config_path=project / "project.toml",
    )

    assert resolved == project / "network.gpkg"


def test_an_absolute_custom_path_is_kept(tmp_path):
    network = _write_network(tmp_path / "network.gpkg")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom(str(network))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network


def test_a_directory_yields_its_vector_and_not_its_raster(tmp_path):
    """The data manager prefers a raster here; the burn needs the linework."""
    folder = tmp_path / "hydrography"
    folder.mkdir()
    _write_raster(folder / "network.tif")
    _write_network(folder / "network.gpkg")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == folder / "network.gpkg"


def test_a_raster_only_source_resolves_to_nothing(tmp_path):
    raster = _write_raster(tmp_path / "network.tif")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom(str(raster))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_the_first_source_holding_a_vector_wins(tmp_path):
    raster = _write_raster(tmp_path / "network.tif")
    network = _write_network(tmp_path / "network.gpkg")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom(str(raster)), _custom(str(network))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network


def test_a_scaffold_template_is_not_picked_up(tmp_path):
    folder = tmp_path / "hydrography"
    folder.mkdir()
    _write_network(folder / "hydrography_custom_EXAMPLE.gpkg")

    resolved = resolve_stream_geometry_path_from_data_sources(
        _cfg([_custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_a_custom_path_pointing_at_nothing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="custom source path not found"):
        resolve_stream_geometry_path_from_data_sources(
            _cfg([_custom("absent.gpkg")]),
            config_path=tmp_path / "project.toml",
        )


def test_no_hydrography_section_resolves_to_nothing(tmp_path):
    cfg = SimpleNamespace(data=SimpleNamespace(hydrography=None), geographic=SimpleNamespace())

    assert (
        resolve_stream_geometry_path_from_data_sources(cfg, config_path=tmp_path / "project.toml")
        is None
    )


def test_an_api_source_without_an_outlet_says_so(tmp_path):
    cfg = _cfg(
        [SimpleNamespace(source="osm", path=None, force_refresh=False)],
        x_outlet=None,
        y_outlet=None,
    )

    with pytest.raises(ValueError, match="x_outlet"):
        resolve_stream_geometry_path_from_data_sources(
            cfg,
            config_path=tmp_path / "project.toml",
        )


def test_an_api_source_downloads_on_the_outlet_box_clipped_to_the_dem(tmp_path, monkeypatch):
    dem = _write_raster(tmp_path / "dem.tif")
    cfg = _cfg(
        [SimpleNamespace(source="osm", path=None, force_refresh=False)],
        dem_init_path=dem,
    )
    seen: dict[str, tuple[float, float, float, float]] = {}

    def _fake_fetch(source, extent):
        assert source.source_id == "osm"
        seen["bbox"] = extent.bbox
        return gpd.GeoDataFrame({"id": [1]}, geometry=[_NETWORK], crs="EPSG:2154")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.api_source.fetch_network",
        _fake_fetch,
    )

    resolved = resolve_stream_geometry_path_from_data_sources(
        cfg,
        config_path=tmp_path / "project.toml",
        cache_dir=tmp_path / "cache",
    )

    assert resolved is not None
    assert resolved.exists()
    assert resolved.parent == tmp_path / "cache"
    # The 30 km outlet box is far wider than the 4 km DEM, so the DEM footprint
    # is what the fetch box ends up being.
    lon_min, lat_min, lon_max, lat_max = seen["bbox"]
    assert lon_max - lon_min < 0.2
    assert lat_max - lat_min < 0.2
    assert str(gpd.read_file(resolved).crs) == "EPSG:4326"


def test_a_downloaded_box_is_not_fetched_twice(tmp_path, monkeypatch):
    cfg = _cfg([SimpleNamespace(source="osm", path=None, force_refresh=False)])
    calls = {"n": 0}

    def _fake_fetch(_source, _extent):
        calls["n"] += 1
        return gpd.GeoDataFrame({"id": [1]}, geometry=[_NETWORK], crs="EPSG:2154")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.api_source.fetch_network",
        _fake_fetch,
    )

    first = resolve_stream_geometry_path_from_data_sources(
        cfg, config_path=tmp_path / "project.toml", cache_dir=tmp_path / "cache"
    )
    second = resolve_stream_geometry_path_from_data_sources(
        cfg, config_path=tmp_path / "project.toml", cache_dir=tmp_path / "cache"
    )

    assert first == second
    assert calls["n"] == 1
