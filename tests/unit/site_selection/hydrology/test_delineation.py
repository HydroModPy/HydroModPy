from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPoint, Point

from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    delineate_candidate_outlet,
    outlet_display_xy,
    outlet_snap_distance_m,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.pipeline import (
    delineate_site_selection_candidates,
)
from tests._helpers.site_selection_cases import delineation_spy, site_flow_products
from tests._helpers.terrain_doubles import fake_flow_products

pytestmark = pytest.mark.fast

OUTLET = CandidateOutlet("station A", 350010.0, 6810025.0, "EPSG:2154", "station_outlets")
FLOW = fake_flow_products(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")


def test_a_candidate_is_delineated_by_the_point_extractor(tmp_path):
    calls: list = []

    result = delineate_candidate_outlet(
        outlet=OUTLET,
        flow_products=site_flow_products("dem_acc.tif"),
        output_root=tmp_path,
        snap_dist_m=250,
        builder=delineation_spy(calls, size=1000.0),
    )

    (call,) = calls
    assert (call["x_outlet"], call["y_outlet"], call["snap_dist"]) == (350010.0, 6810025.0, 250)
    assert str(call["accumulation"].path) == "dem_acc.tif"
    assert str(call["accumulation"].directions.path) == "direc.tif"
    assert call["crs_project"] == "EPSG:2154"
    assert call["output_dir"] == tmp_path / "station_A"
    assert result.area_km2 == pytest.approx(1.0)
    assert result.status == "delineated"


def test_a_candidate_can_snap_to_the_reference_network_before_the_dem(tmp_path):
    calls: list = []
    river = LineString([(350000.0, 6810000.0), (350100.0, 6810000.0)])

    result = delineate_candidate_outlet(
        outlet=OUTLET,
        flow_products=FLOW,
        output_root=tmp_path,
        snap_dist_m=150,
        builder=delineation_spy(calls),
        area_reader=lambda _path: 123.4,
        reference_network=gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154"),
        reference_network_source="bdtopage",
    )

    assert (calls[0]["x_outlet"], calls[0]["y_outlet"]) == (350010.0, 6810000.0)
    assert calls[0]["snap_dist"] == 150
    assert result.outlet.attributes["reference_network_source"] == "bdtopage"
    assert result.outlet.attributes["reference_network_snap_distance_m"] == 25.0


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


def test_a_batch_delineates_every_candidate(tmp_path):
    calls: list = []
    candidates = [OUTLET, CandidateOutlet("station_B", 351000.0, 6811000.0, "EPSG:2154", "s")]

    results = delineate_site_selection_candidates(
        candidates,
        flow_products=FLOW,
        output_root=tmp_path,
        snap_dist_m=250,
        crs_project="EPSG:2154",
        delineation_builder=delineation_spy(calls),
        area_reader=lambda _path: 42.0,
    )

    assert [(one.site_id, one.area_km2) for one in results] == [
        ("station A", 42.0),
        ("station_B", 42.0),
    ]
    assert [call["x_outlet"] for call in calls] == [350010.0, 351000.0]


def _feature(geometry: dict) -> dict:
    return {"type": "Feature", "geometry": geometry}


@pytest.mark.parametrize(
    ("name", "content", "snapped"),
    [
        ("snap.geojson", {"type": "Point", "coordinates": [350013.0, 6810029.0]}, True),
        (
            "snap.geojson",
            _feature({"type": "MultiPoint", "coordinates": [[350013.0, 6810029.0]]}),
            True,
        ),
        (
            "snap.json",
            {
                "type": "FeatureCollection",
                "features": [
                    1,
                    _feature(None),
                    _feature({"type": "Point", "coordinates": [350013.0, 6810029.0]}),
                ],
            },
            True,
        ),
        ("snap.geojson", "not json", False),
        ("snap.geojson", {"type": "FeatureCollection", "features": {}}, False),
        ("snap.geojson", {"type": "Point", "coordinates": ["a", "b"]}, False),
        ("snap.geojson", {"type": "MultiPoint", "coordinates": [["a", "b"]]}, False),
        ("snap.geojson", [], False),
        ("snap.gpkg", Point(350013.0, 6810029.0), True),
        ("snap.gpkg", MultiPoint([(350013.0, 6810029.0)]), True),
        ("snap.gpkg", LineString([(0, 0), (1, 1)]), False),
        ("snap.shp", "not a vector", False),
        ("missing.geojson", None, False),
    ],
)
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
