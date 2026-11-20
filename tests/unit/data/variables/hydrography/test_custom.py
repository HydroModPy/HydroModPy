"""A user file or folder as hydrography source: vector linework or a stream raster.

A folder is searched for a raster first, then for a vector. A raster comes back
as a path, a vector as a GeoDataFrame.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig
from hydromodpy.data.variables.hydrography.custom import (
    _RASTER_EXTENSIONS,
    _VECTOR_EXTENSIONS,
    load_file,
)
from tests._helpers.data_hydrography_builders import _make_lines_gdf, _write_dummy_tif

pytestmark = pytest.mark.fast


def test_a_folder_with_a_vector_is_read(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    _make_lines_gdf().to_file(folder / "streams.shp")

    gdf = load_file(HydrographySourceConfig(source="file", path=folder))

    assert not gdf.empty


def test_a_folder_with_a_raster_returns_its_path(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    _write_dummy_tif(folder / "streams.tif")

    result = load_file(HydrographySourceConfig(source="file", path=folder))

    assert isinstance(result, Path)
    assert result.suffix == ".tif"


def test_a_vector_file_returns_a_dataframe(tmp_path):
    shp = tmp_path / "rivers.shp"
    _make_lines_gdf().to_file(shp)

    result = load_file(HydrographySourceConfig(source="file", path=shp))

    assert isinstance(result, gpd.GeoDataFrame)


def test_a_folder_prefers_the_raster(tmp_path):
    _make_lines_gdf().to_file(tmp_path / "rivers.shp")
    _write_dummy_tif(tmp_path / "streams.tif")

    result = load_file(HydrographySourceConfig(source="file", path=tmp_path))

    assert isinstance(result, Path)


def test_vector_extensions():
    assert {"*.shp", "*.gpkg", "*.geojson"} <= set(_VECTOR_EXTENSIONS)


def test_raster_extensions():
    assert {"*.tif", "*.tiff"} <= set(_RASTER_EXTENSIONS)


def test_an_empty_folder_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(FileNotFoundError, match="No vector or raster file"):
        load_file(HydrographySourceConfig(source="file", path=empty))
