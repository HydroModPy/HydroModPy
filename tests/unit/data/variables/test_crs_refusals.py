"""A DEM, a geology file or a river network without a CRS is refused by name.

They used to be labeled EPSG:2154 (DEM, geology) or EPSG:4326 (river network)
without a word. A file in another frame was then cut by the wrong box, or
placed kilometers away.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.hydrography.custom import load_file
from tests._helpers.geotiffs import write_geotiff

pytestmark = pytest.mark.fast


@pytest.fixture
def files(tmp_path):
    """One file of each kind, none with a CRS, in tmp_path."""
    for name in ("dem.tif", "geology.tif", "rivers.tif"):
        write_geotiff(tmp_path / name, np.ones((4, 4)), cell=25.0, crs=None)
    gpd.GeoDataFrame({"code": [1]}, geometry=[box(0, 0, 10, 10)]).to_file(tmp_path / "geology.gpkg")
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])]).to_file(tmp_path / "rivers.gpkg")
    return tmp_path


REFUSALS = [
    pytest.param(load_custom_dem, "dem.tif", {}, r"dem: .*dem\.tif declares no CRS", id="dem"),
    pytest.param(
        load_custom_geology, "geology.tif", {}, "geology: .*declares no CRS", id="geology raster"
    ),
    pytest.param(
        load_custom_geology,
        "geology.gpkg",
        {"code_field": "code"},
        "geology: .*declares no CRS",
        id="geology vector",
    ),
    pytest.param(
        load_file, "rivers.gpkg", {}, "hydrography: .*declares no CRS", id="rivers vector"
    ),
    pytest.param(load_file, "rivers.tif", {}, "hydrography: .*declares no CRS", id="rivers raster"),
]


@pytest.mark.parametrize(("loader", "name", "kwargs", "match"), REFUSALS)
def test_refusals(files, loader, name, kwargs, match):
    with pytest.raises(DataContractViolation, match=match) as info:
        loader(SimpleNamespace(path=files / name), **kwargs)

    assert exit_code_for(info.value) == EXIT_VALIDATION


def test_a_dem_with_a_crs_keeps_it(tmp_path):
    path = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, crs="EPSG:32630")

    (record,) = load_custom_dem(SimpleNamespace(path=path))

    assert "32630" in record.crs
