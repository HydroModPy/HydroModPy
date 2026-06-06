from __future__ import annotations

import json

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.candidate_builders import (
    write_dem_network_geojson,
)
from hydromodpy.spatial.site_selection.config import HydrologyConfig
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

from ._test_candidate_audit_builders import write_accumulation_raster


def _feature_points(geometry: dict) -> list[list[float]]:
    if geometry["type"] == "Point":
        return [geometry["coordinates"]]
    if geometry["type"] == "LineString":
        return list(geometry["coordinates"])
    return []


@pytest.mark.fast
def test_dem_network_geojson_exports_dem_stream_segments(tmp_path):
    acc_path = write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [1.0, 1.0, 1.0],
                [1.0, 50.0, 60.0],
                [1.0, 1.0, 70.0],
            ],
            dtype="float64",
        ),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    path = write_dem_network_geojson(
        tmp_path / "dem_network.geojson",
        flow_products=flow_products,
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["hydromodpy_geometry_role"] == "dem_network"
    assert payload["hydromodpy_coordinate_crs"] == "EPSG:2154"
    assert any(feature["geometry"]["type"] == "LineString" for feature in payload["features"])


@pytest.mark.fast
def test_dem_network_geojson_honors_search_geometry(tmp_path):
    box = pytest.importorskip("shapely.geometry").box
    acc_path = write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [90.0, 1.0, 1.0],
                [90.0, 1.0, 80.0],
                [90.0, 1.0, 80.0],
            ],
            dtype="float64",
        ),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    path = write_dem_network_geojson(
        tmp_path / "dem_network.geojson",
        flow_products=flow_products,
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
        search_geometry=box(20.0, 0.0, 30.0, 20.0),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    coordinates = [
        point for feature in payload["features"] for point in _feature_points(feature["geometry"])
    ]
    assert coordinates
    assert all(x >= 20.0 for x, _y in coordinates)
