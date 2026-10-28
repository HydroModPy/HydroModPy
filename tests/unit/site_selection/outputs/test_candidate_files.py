"""The generated DEM network is written as GeoJSON stream segments."""

from __future__ import annotations

import json

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.outputs.candidate_files import (
    write_generated_network_geojson,
)
from tests._helpers.site_selection_cases import site_flow_products, write_accumulation_raster

pytestmark = pytest.mark.fast


def _network(tmp_path, accumulation, **kwargs) -> dict:
    acc_path = write_accumulation_raster(tmp_path / "acc.tif", np.array(accumulation))
    path = write_generated_network_geojson(
        tmp_path / "generated_dem_network.geojson",
        flow_products=site_flow_products(acc_path),
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
        **kwargs,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_generated_network_is_written_as_stream_segments(tmp_path):
    payload = _network(tmp_path, [[1.0, 1.0, 1.0], [1.0, 50.0, 60.0], [1.0, 1.0, 70.0]])

    assert payload["hydromodpy_geometry_role"] == "generated_dem_network"
    assert payload["hydromodpy_coordinate_crs"] == "EPSG:2154"
    assert any(feature["geometry"]["type"] == "LineString" for feature in payload["features"])


def test_the_generated_network_stays_inside_the_search_geometry(tmp_path):
    accumulation = [[90.0, 1.0, 1.0], [90.0, 1.0, 80.0], [90.0, 1.0, 80.0]]

    payload = _network(tmp_path, accumulation, search_geometry=box(20.0, 0.0, 30.0, 20.0))

    geometries = [feature["geometry"] for feature in payload["features"]]
    xs = [
        point[0]
        for geometry in geometries
        for point in (
            [geometry["coordinates"]] if geometry["type"] == "Point" else geometry["coordinates"]
        )
    ]
    assert xs
    assert min(xs) >= 20.0
