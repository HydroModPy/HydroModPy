"""Read the network map of the alpha diagnostic from ``[[data.hydrography.sources]]``."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
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
    return SimpleNamespace(source="custom", path=path, force_refresh=False)


def test_a_relative_custom_path_anchors_on_the_toml_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _write_network(project / "network.gpkg")

    resolved = resolve_network_map_path(
        _cfg([_custom("network.gpkg")]),
        config_path=project / "project.toml",
    )

    assert resolved == project / "network.gpkg"


def test_an_absolute_custom_path_is_kept(tmp_path):
    network = _write_network(tmp_path / "network.gpkg")

    resolved = resolve_network_map_path(
        _cfg([_custom(str(network))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network


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


def test_the_first_source_holding_a_vector_wins(tmp_path):
    raster = _write_raster(tmp_path / "network.tif")
    network = _write_network(tmp_path / "network.gpkg")

    resolved = resolve_network_map_path(
        _cfg([_custom(str(raster)), _custom(str(network))]),
        config_path=tmp_path / "project.toml",
    )

    assert resolved == network


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
    assert "custom source path not found" in caplog.text


def test_no_hydrography_section_resolves_to_nothing(tmp_path):
    cfg = SimpleNamespace(data=SimpleNamespace(hydrography=None), geographic=SimpleNamespace())

    assert resolve_network_map_path(cfg, config_path=tmp_path / "project.toml") is None


def test_an_api_source_is_never_downloaded_and_says_so(tmp_path, monkeypatch, caplog):
    def _no_fetch(*_args, **_kwargs):
        raise AssertionError("alpha must not download a network")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.api_source.fetch_network",
        _no_fetch,
    )
    cfg = _cfg([SimpleNamespace(source="osm", path=None, force_refresh=False)])

    with caplog.at_level(logging.INFO):
        resolved = resolve_network_map_path(cfg, config_path=tmp_path / "project.toml")

    assert resolved is None
    assert "needs a custom vector source" in caplog.text


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
project_root = "{project}"

[geographic.catchment]
catch_def = "dem"
dem_init_path = "dem.tif"

[[data.hydrography.sources]]
source = "custom"
path = "{declared}"
"""


@pytest.mark.parametrize("declared", ["streams.gpkg", "data/hydrography/streams.gpkg"])
def test_the_map_is_the_same_file_from_any_working_directory(tmp_path, monkeypatch, declared):
    """The path is anchored once at load, so the cwd never picks another file."""
    from hydromodpy.config import HydroModPyConfig

    project = tmp_path / "project"
    (project / "data" / "hydrography").mkdir(parents=True)
    (project / "dem.tif").touch()
    _write_network(project / "data" / "hydrography" / "streams.gpkg")
    decoy = tmp_path / "elsewhere"
    decoy.mkdir()
    _write_network(decoy / "streams.gpkg")
    cfg_path = project / "project.toml"
    cfg_path.write_text(
        _PROJECT_TOML.format(project=project.as_posix(), declared=declared), encoding="utf-8"
    )

    resolved = []
    for cwd in (decoy, project):
        monkeypatch.chdir(cwd)
        cfg = HydroModPyConfig.from_toml(cfg_path)
        resolved.append(resolve_network_map_path(cfg, config_path=cfg_path))

    assert resolved[0] == resolved[1]
    assert resolved[0].parent != decoy
