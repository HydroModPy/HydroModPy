"""Read the network map of the alpha diagnostic from ``[[data.hydrography.sources]]``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.data.variables.hydrography.resolver import (
    resolve_network_map_path,
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
    return SimpleNamespace(source="file", path=path, force_refresh=False)


def test_a_directory_yields_its_vector_and_not_its_raster(tmp_path):
    """The data manager prefers a raster here; alpha needs the linework."""
    folder = tmp_path / "hydrography"
    folder.mkdir()
    _write_raster(folder / "network.tif")
    _write_network(folder / "network.gpkg")

    resolved = resolve_network_map_path(
        _cfg([_custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == folder / "network.gpkg"


def test_a_raster_only_source_resolves_to_nothing(tmp_path):
    raster = _write_raster(tmp_path / "network.tif")

    resolved = resolve_network_map_path(
        _cfg([_custom(str(raster))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_a_scaffold_template_is_not_picked_up(tmp_path):
    folder = tmp_path / "hydrography"
    folder.mkdir()
    _write_network(folder / "hydrography_custom_EXAMPLE.gpkg")

    resolved = resolve_network_map_path(
        _cfg([_custom(str(folder))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved is None


def test_a_custom_path_pointing_at_nothing_is_a_warning(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        resolved = resolve_network_map_path(
            _cfg([_custom("absent.gpkg")]),
            config_path=tmp_path / "project.toml",
        )

    assert resolved is None
    assert "file source path not found" in caplog.text


def test_a_custom_source_after_an_api_source_still_wins(tmp_path):
    network = _write_network(tmp_path / "network.gpkg")

    resolved = resolve_network_map_path(
        _cfg(
            [SimpleNamespace(source="osm", path=None, force_refresh=False), _custom(str(network))]
        ),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network


_PROJECT_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{project}"

[site]
name = "site_a"

[geographic.catchment]
kind = "dem"

[[data.dem.sources]]
source = "file"
path = "inputs/dem.tif"

[[data.hydrography.sources]]
source = "file"
path = "{declared}"
"""
