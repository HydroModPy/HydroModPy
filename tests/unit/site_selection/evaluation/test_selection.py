"""Selection of delineated catchments: criteria, ranking, overlap, spacing and quota."""

from __future__ import annotations

import pytest
from shapely.geometry import box

from hydromodpy.spatial.site_selection.config.criteria_config import CriteriaConfig
from hydromodpy.spatial.site_selection.config.outlets_config import SpatialSelectionConfig
from hydromodpy.spatial.site_selection.domain.delineated_catchment import DelineatedCatchment
from hydromodpy.spatial.site_selection.evaluation.selection import select_delineated_catchments
from tests._helpers.site_selection_cases import make_catchment, write_point_geojson

pytestmark = pytest.mark.fast

REPORT_AREA = {"area": {"mode": "report_only"}}
HALVES = {"a": box(0.0, 0.0, 10.0, 10.0), "b": box(5.0, 0.0, 15.0, 10.0)}


def _select(catchments, criteria=REPORT_AREA, principle="criteria_crossing", **kwargs):
    spatial = SpatialSelectionConfig(**kwargs.pop("spatial", {}))
    return select_delineated_catchments(
        catchments,
        criteria=CriteriaConfig.model_validate(criteria),
        spatial_selection=spatial,
        selection_principle=principle,
        **kwargs,
    )


def _ids(catchments):
    return [catchment.site_id for catchment in catchments]


def _decision(result, site_id):
    return next(decision for decision in result.decisions if decision.site_id == site_id)


def _component(result, criterion_id, site_id=None):
    return next(
        item
        for item in result.criteria_components
        if item.criterion_id == criterion_id and site_id in (None, item.site_id)
    )


def test_an_area_outside_the_hard_bounds_rejects_the_catchment():
    area = {"mode": "hard_reject", "hard_min_area_km2": 75.0, "hard_max_area_km2": 125.0}
    result = _select(
        [make_catchment("too_small", area_km2=50.0), make_catchment("ok")], {"area": area}
    )

    assert (_ids(result.selected), _ids(result.rejected)) == (["ok"], ["too_small"])
    assert _decision(result, "too_small").blocking_flags == ["area"]


@pytest.mark.parametrize(
    ("attributes", "criteria", "flag"),
    [
        ({"major_dam_upstream": "true"},
         {"influence": {"mode": "hard_reject", "reject_major_dam_upstream": True}}, "influence"),
        ({"flow_station_id": "J123456701", "influence_generale_site": "1"},
         {"observations": {"station_influence": {"mode": "hard_reject"}}}, "station_influence"),
    ],
)  # fmt: skip
def test_a_blocking_criterion_rejects_the_catchment(attributes, criteria, flag):
    influenced = make_catchment("influenced", attributes=attributes)

    result = _select([influenced, make_catchment("ok")], {**REPORT_AREA, **criteria})

    assert _ids(result.selected) == ["ok"]
    assert _decision(result, "influenced").blocking_flags == [flag]


def test_a_piezometer_warning_keeps_the_catchment_and_its_audit():
    far = make_catchment("far", attributes={"nearest_piezometer_distance_km": 5.0})
    piezometer = {"piezometer_mode": "warning", "piezometer_max_distance_km": 2.0}

    result = _select([far], {**REPORT_AREA, "observations": piezometer})

    assert _ids(result.selected) == ["far"]
    assert result.decisions[0].warning_flags == ["piezometer"]
    assert _component(result, "piezometer").criterion_status == "warning"


def test_the_area_score_ranks_the_catchment_nearest_the_preferred_area_first():
    area = {"mode": "score", "preferred_area_km2": 100.0, "score_half_width_fraction": 0.5}
    far, near = make_catchment("far", area_km2=140.0), make_catchment("near", area_km2=100.0)

    result = _select([far, near], {"area": area}, spatial={"max_selected_sites": 1})

    assert (_ids(result.selected), _ids(result.rejected)) == (["near"], ["far"])
    record = _decision(result, "near").to_record()
    assert record["rank_score"] == pytest.approx(1.0)
    assert record["criteria_summary_json"]["area"] == "scored"


def test_the_flow_station_distance_is_measured_to_the_snapped_outlet(tmp_path):
    snap_path = write_point_geojson(tmp_path / "outlet_snap.geojson", coordinates=[3000.0, 0.0])
    attributes = {
        "flow_station_id": "J001001001",
        "flow_station_x": "0.0",
        "flow_station_y": "0.0",
        "flow_station_crs": "EPSG:2154",
        "flow_station_record_years": "20.0",
        "station_to_outlet_distance_km": "0.0",
    }
    catchment = make_catchment(
        "far_after_snap", source="hubeau_hydrometrie", attributes=attributes,
        outlet_snap_shp=str(snap_path),
    )  # fmt: skip
    flow_station = {
        "mode": "hard_reject",
        "min_record_years": 5.0,
        "max_station_to_outlet_distance_km": 1.0,
    }

    result = _select(
        [catchment],
        {**REPORT_AREA, "observations": {"flow_station": flow_station}},
        "observation_led",
    )

    assert _ids(result.rejected) == ["far_after_snap"]
    component = _component(result, "flow_station")
    assert component.blocking is True
    assert component.evidence_json["station_to_outlet_distance_km"] == pytest.approx(3.0)
    assert "exceeds 1" in component.reason


@pytest.mark.parametrize(
    ("station", "distance_km"),
    [
        (
            {
                "station_x": 3.0,
                "station_y": 46.5,
                "flow_station_crs": " ",
                "station_crs": "EPSG:4326",
            },
            1.0,
        ),
        ({"station_x": 700000.0, "station_y": 6600000.0, "station_crs": "epsg:2154"}, 1.0),
        ({"station_x": 700000.0, "station_y": 6600000.0, "station_crs": "IGNF:LAMB93"}, 1.0),
        ({"station_x": 3.0, "station_y": 46.5, "station_crs": "not a crs"}, None),
        ({"hydro_station_x": "n/a", "station_x": 700500.0, "station_y": 6600000.0}, 0.5),
        ({"flow_station_id": "J1"}, 0.0),
        ({"source": "station_outlets"}, 0.0),
        ({}, None),
    ],
)
def test_the_flow_station_is_brought_into_the_outlet_crs(station, distance_km):
    attributes = {key: value for key, value in station.items() if key != "source"}
    source = station.get("source", "test")
    catchment = make_catchment(
        "site", x=701000.0, y=6600000.0, source=source, attributes=attributes
    )

    result = _select([catchment], {**REPORT_AREA, "observations": {"flow_station": {}}})

    measured = _component(result, "flow_station").evidence_json["station_to_outlet_distance_km"]
    assert measured == (None if distance_km is None else pytest.approx(distance_km, abs=1e-3))


@pytest.mark.parametrize(("mode", "selected", "flag"), [
    ("hard_reject", ["a"], "blocking_flags"),
    ("warning", ["a", "b"], "warning_flags"),
])  # fmt: skip
def test_an_overlapping_lower_ranked_basin_follows_the_overlap_mode(mode, selected, flag):
    result = _select(
        [make_catchment("a", priority=10.0), make_catchment("b", priority=1.0)],
        spatial={"max_pairwise_basin_overlap_fraction": 0.05, "overlap_mode": mode},
        basin_geometries=HALVES,
    )

    assert _ids(result.selected) == selected
    assert getattr(_decision(result, "b"), flag) == ["basin_overlap"]


def test_a_basin_without_geometry_skips_the_overlap_check():
    catchments = [make_catchment(site_id, priority=10.0 - i) for i, site_id in enumerate("abcde")]
    far = box(100.0, 0.0, 110.0, 10.0)

    result = _select(
        catchments,
        spatial={"max_pairwise_basin_overlap_fraction": 0.05},
        basin_geometries={"b": HALVES["b"], "c": HALVES["b"], "d": far},
    )

    assert _ids(result.selected) == ["a", "b", "d", "e"]
    assert _component(result, "basin_overlap", "c").evidence_json["max_overlap_site_id"] == "b"
    assert [item.site_id for item in result.criteria_components if item.criterion_id == "basin_overlap"] == ["b", "c", "d"]  # fmt: skip
    assert _component(result, "basin_overlap", "b").raw_value == 0.0


def test_a_delineation_failure_is_carried_as_a_rejection():
    failed = make_catchment(
        "failed", area_km2=None, status="rejected_delineation_failed", failure_reason="snap failed"
    )

    result = _select([failed])

    assert (result.selected, result.rejected) == ([], [failed])
    assert isinstance(result.rejected[0], DelineatedCatchment)
    assert result.decisions[0].decision_stage == "delineation"


def test_the_target_count_rejects_the_lowest_ranked_catchments():
    catchments = [make_catchment(name, priority=p) for name, p in (("best", 10), ("next", 5), ("third", 1))]  # fmt: skip

    result = _select(catchments, spatial={"max_selected_sites": 2})

    assert (_ids(result.selected), _ids(result.rejected)) == (["best", "next"], ["third"])
    assert _decision(result, "third").blocking_flags == ["target_count"]
    assert _decision(result, "third").decision_reason == "target count 2 reached"


def test_an_outlet_too_close_to_a_selected_one_is_rejected():
    catchments = [make_catchment(name, priority=p, x=x) for name, p, x in (("a", 10, 0), ("b", 5, 500), ("c", 1, 2000), ("d", 0, -1000))]  # fmt: skip

    result = _select(catchments, spatial={"min_outlet_distance_km": 1.0})

    assert (_ids(result.selected), _ids(result.rejected)) == (["a", "c", "d"], ["b"])
    assert _decision(result, "b").blocking_flags == ["outlet_spacing"]
    assert "below 1.000 km" in _decision(result, "b").decision_reason


def test_the_grid_quota_keeps_one_site_per_cell():
    points = (("a", 10, 100, 100), ("b", 9, 500, 500), ("c", 8, 1500, 100))
    catchments = [make_catchment(name, priority=p, x=x, y=y) for name, p, x, y in points]
    quota = {
        "spatial_quota_mode": "grid",
        "spatial_quota_cell_size_km": 1.0,
        "spatial_quota_max_sites_per_cell": 1,
    }

    result = _select(catchments, spatial=quota)

    assert (_ids(result.selected), _ids(result.rejected)) == (["a", "c"], ["b"])
    assert _decision(result, "b").blocking_flags == ["spatial_quota"]
    assert _component(result, "spatial_quota", "b").evidence_json["cell_key"] == "grid:0:0"
