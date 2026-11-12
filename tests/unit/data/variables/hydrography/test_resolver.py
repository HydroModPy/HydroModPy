"""The network map of the alpha diagnostic, read from ``[[data.hydrography.sources]]``.

Only vector linework is a network map. A raster, a template or a missing path gives None.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.data.variables.hydrography.resolver import resolve_network_map_path

NETWORK = LineString([(350000.0, 6800000.0), (350000.0, 6805000.0)])


def write_network(path: Path) -> Path:
    gpd.GeoDataFrame({"id": [1]}, geometry=[NETWORK], crs="EPSG:2154").to_file(path)
    return path


def write_raster(path: Path) -> Path:
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


def cfg(
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


def custom(path):
    return SimpleNamespace(source="file", path=path, force_refresh=False)


def test_a_directory_yields_its_vector(tmp_path):
    # The data manager prefers a raster here, alpha needs the linework.
    folder = tmp_path / "hydrography"
    folder.mkdir()
    write_raster(folder / "network.tif")
    write_network(folder / "network.gpkg")

    resolved = resolve_network_map_path(
        cfg([custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == folder / "network.gpkg"


def test_a_raster_resolves_to_nothing(tmp_path):
    raster = write_raster(tmp_path / "network.tif")

    resolved = resolve_network_map_path(
        cfg([custom(str(raster))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_a_template_is_skipped(tmp_path):
    folder = tmp_path / "hydrography"
    folder.mkdir()
    write_network(folder / "hydrography_custom_EXAMPLE.gpkg")

    resolved = resolve_network_map_path(
        cfg([custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_a_missing_path_is_a_warning(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        resolved = resolve_network_map_path(
            cfg([custom("absent.gpkg")]),
            config_path=tmp_path / "project.toml",
        )

    assert resolved is None
    assert "file source path not found" in caplog.text


def test_a_file_source_after_an_api_source_wins(tmp_path):
    network = write_network(tmp_path / "network.gpkg")

    resolved = resolve_network_map_path(
        cfg([SimpleNamespace(source="osm", path=None, force_refresh=False), custom(str(network))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network
