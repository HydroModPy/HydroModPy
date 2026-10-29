"""Candidate outlets are delineated on the flow products built for the selection."""

from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPoint, Point

from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_display_xy,
    outlet_snap_distance_m,
)
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    delineate_candidate_outlet,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    build_site_selection_flow_products,
)
from tests._helpers.site_selection_cases import delineation_spy, flow_spy, site_flow_products
from tests._helpers.terrain_doubles import fake_flow_products

pytestmark = pytest.mark.fast

OUTLET = CandidateOutlet("station A", 350010.0, 6810025.0, "EPSG:2154", "station_outlets")
FLOW = fake_flow_products(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")


def test_a_candidate_is_delineated_by_the_point_extractor(tmp_path):
    calls: list = []

    result = delineate_candidate_outlet(
        outlet=OUTLET, flow_products=site_flow_products("dem_acc.tif"), output_root=tmp_path,
        snap_dist_m=250, builder=delineation_spy(calls, size=1000.0),
    )  # fmt: skip

    (call,) = calls
    assert (call["x_outlet"], call["y_outlet"], call["snap_dist"]) == (350010.0, 6810025.0, 250)
    accumulation = call["accumulation"]
    assert (str(accumulation.path), str(accumulation.directions.path)) == (
        "dem_acc.tif",
        "direc.tif",
    )
    assert (call["crs_project"], call["output_dir"]) == ("EPSG:2154", tmp_path / "station_A")
    assert result.area_km2 == pytest.approx(1.0)
    assert result.status == "delineated"


@pytest.mark.parametrize(
    ("builder", "snap", "reason"),
    [
        (delineation_spy(), 0, "snap_dist_m must be > 0"),
        (lambda **_: (_ for _ in ()).throw(RuntimeError("snap failed")), 250, "snap failed"),
    ],
)
def test_a_failed_delineation_is_a_rejected_record(tmp_path, builder, snap, reason):
    result = try_delineate_candidate_outlet(
        outlet=OUTLET, flow_products=FLOW, output_root=tmp_path, snap_dist_m=snap, builder=builder
    )

    assert result.status == "rejected_delineation_failed"
    assert reason in result.failure_reason
    assert result.to_record()["candidate_id"] == "station A"


def _feature(geometry: dict | None) -> dict:
    return {"type": "Feature", "geometry": geometry}


SNAP = [350013.0, 6810029.0]
POINT = {"type": "Point", "coordinates": SNAP}


@pytest.mark.parametrize(
    ("name", "content", "snapped"),
    [
        ("snap.geojson", POINT, True),
        ("snap.geojson", _feature({"type": "MultiPoint", "coordinates": [SNAP]}), True),
        ("snap.json", {"type": "FeatureCollection", "features": [1, _feature(None), _feature(POINT)]}, True),
        ("snap.geojson", "not json", False),
        ("snap.geojson", {"type": "FeatureCollection", "features": {}}, False),
        ("snap.geojson", {"type": "Point", "coordinates": ["a", "b"]}, False),
        ("snap.geojson", {"type": "MultiPoint", "coordinates": [["a", "b"]]}, False),
        ("snap.geojson", [], False),
        ("snap.gpkg", Point(*SNAP), True),
        ("snap.gpkg", MultiPoint([SNAP]), True),
        ("snap.gpkg", LineString([(0, 0), (1, 1)]), False),
        ("snap.shp", "not a vector", False),
        ("missing.geojson", None, False),
    ],
)  # fmt: skip
def test_the_snapped_outlet_is_read_from_what_the_delineation_wrote(
    tmp_path, name, content, snapped
):
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    elif isinstance(content, dict | list):
        path.write_text(json.dumps(content), encoding="utf-8")
    elif content is not None:
        gpd.GeoDataFrame(geometry=[content], crs="EPSG:2154").to_file(path)
    catchment = DelineatedCatchment(site_id="a", outlet=OUTLET, outlet_snap_shp=str(path))

    distance = outlet_snap_distance_m(catchment)

    if snapped:
        assert outlet_display_xy(catchment) == (350013.0, 6810029.0)
        assert distance == pytest.approx(5.0)
    else:
        assert outlet_display_xy(catchment) == (OUTLET.x, OUTLET.y)
        assert distance is None


@pytest.mark.parametrize(
    ("conditioning", "expected"), [("breach", "breach"), ("existing_default", "fill")]
)
def test_the_flow_products_are_built_by_the_regional_builder(tmp_path, conditioning, expected):
    calls: dict = {}

    bundle = build_site_selection_flow_products(
        dem_init_path=tmp_path / "dem.tif",
        output_dir=tmp_path / "flow",
        hydrology=HydrologyConfig(hydrologic_conditioning=conditioning),
        crs_project="EPSG:2154",
        builder=flow_spy(calls, direc=tmp_path / "dem_direc.tif"),
    )

    assert (calls["dem_init_path"], calls["dem_out_dir_path"]) == (
        tmp_path / "dem.tif",
        tmp_path / "flow",
    )
    assert (calls["dem_correc_type"], calls["crs_project"]) == (expected, "EPSG:2154")
    assert bundle.dem_correction_type == expected
    assert bundle.to_manifest_record()["flow_direction_path"].endswith("dem_direc.tif")
