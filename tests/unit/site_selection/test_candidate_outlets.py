from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from tests.unit.site_selection._records import make_point_record


@pytest.mark.fast
def test_candidate_outlets_from_point_records_use_station_metadata():
    record = make_point_record(
        "J123456701",
        x=352000.0,
        y=6812000.0,
        metadata={"station_name": "La Riviere a Exemple"},
        n_values=2,
    )

    candidates = candidate_outlets_from_point_records([record], candidate_prefix="station")

    assert len(candidates) == 1
    assert candidates[0].candidate_id == "station_J123456701"
    assert candidates[0].source_feature_id == "J123456701"
    assert candidates[0].source_label == "La Riviere a Exemple"
    assert candidates[0].priority == pytest.approx(2.0)
    assert candidates[0].attributes["flow_station_id"] == "J123456701"
    assert candidates[0].attributes["flow_station_crs"] == "EPSG:2154"


@pytest.mark.fast
def test_candidate_outlets_from_hubeau_records_use_lambert93_metadata_when_requested():
    record = make_point_record(
        "J123456701",
        x=-1.65,
        y=48.12,
        crs="EPSG:4326",
        metadata={
            "station_name": "Station HubEau",
            "x_l93": "354200.0",
            "y_l93": "6790140.0",
            "influence_generale_site": "0",
        },
    )

    candidates = candidate_outlets_from_point_records(
        [record],
        candidate_prefix="station",
        target_crs="EPSG:2154",
    )

    assert len(candidates) == 1
    assert candidates[0].x == pytest.approx(354200.0)
    assert candidates[0].y == pytest.approx(6790140.0)
    assert candidates[0].crs == "EPSG:2154"
    assert candidates[0].attributes["source_location_crs"] == "EPSG:4326"
    assert candidates[0].attributes["flow_station_influence_generale_site"] == "0"


@pytest.mark.fast
def test_candidate_outlets_fall_back_when_lambert93_metadata_is_inconsistent():
    record = make_point_record(
        "I923301301",
        x=-1.233497944,
        y=48.579264655,
        crs="EPSG:4326",
        metadata={
            "station_name": "La Selune a Ducey",
            "x_l93": "336576.0",
            "y_l93": "2403827.0",
        },
    )

    candidates = candidate_outlets_from_point_records(
        [record],
        candidate_prefix="station",
        target_crs="EPSG:2154",
    )

    assert len(candidates) == 1
    assert candidates[0].x == pytest.approx(387868.83, abs=0.01)
    assert candidates[0].y == pytest.approx(6839375.02, abs=0.01)
    assert candidates[0].crs == "EPSG:2154"


@pytest.mark.fast
def test_thin_candidate_outlets_keeps_highest_priority_when_too_close():
    candidates = [
        CandidateOutlet("low", 0.0, 0.0, "EPSG:2154", "test", priority=1.0),
        CandidateOutlet("high", 500.0, 0.0, "EPSG:2154", "test", priority=10.0),
        CandidateOutlet("far", 5000.0, 0.0, "EPSG:2154", "test", priority=0.0),
    ]

    selected = thin_candidate_outlets(candidates, min_distance_km=1.0)

    assert [candidate.candidate_id for candidate in selected] == ["far", "high"]


@pytest.mark.fast
def test_thin_candidate_outlets_supports_wgs84_distance():
    candidates = [
        CandidateOutlet("a", -1.0, 48.0, "EPSG:4326", "test", priority=1.0),
        CandidateOutlet("b", -1.001, 48.0, "EPSG:4326", "test", priority=2.0),
    ]

    selected = thin_candidate_outlets(candidates, min_distance_km=1.0)

    assert [candidate.candidate_id for candidate in selected] == ["b"]
