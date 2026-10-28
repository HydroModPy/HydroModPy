from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from tests._helpers.site_selection_cases import make_point_record

pytestmark = pytest.mark.fast


def test_a_station_record_becomes_a_candidate_named_after_its_station():
    record = make_point_record(
        "J123456701", x=352000.0, y=6812000.0, metadata={"station_name": "La Riviere"}, n_values=2
    )

    (candidate,) = candidate_outlets_from_point_records([record], candidate_prefix="station")

    assert candidate.candidate_id == "station_J123456701"
    assert (candidate.source_feature_id, candidate.source_label) == ("J123456701", "La Riviere")
    assert candidate.priority == 2.0
    assert candidate.to_record()["attributes"]["flow_station_crs"] == "EPSG:2154"


def test_records_without_a_place_are_skipped_and_odd_ids_are_cleaned():
    no_crs = SimpleNamespace(station_id="x", location=SimpleNamespace(crs="", x=0.0, y=0.0))
    odd_id = make_point_record("  ", x=1.0, y=2.0)

    candidates = candidate_outlets_from_point_records(
        [SimpleNamespace(location=None), no_crs, odd_id]
    )

    assert [one.candidate_id for one in candidates] == ["obs_candidate"]


def test_a_hubeau_record_reads_its_lambert93_metadata_when_lambert93_is_asked():
    metadata = {"x_l93": "352000.5", "y_l93": "6812000.25", "influence_generale_site": "0"}
    record = make_point_record("J1", x=-1.65, y=48.12, crs="EPSG:4326", metadata=metadata)

    (candidate,) = candidate_outlets_from_point_records([record], target_crs="EPSG:2154")

    assert (candidate.x, candidate.y, candidate.crs) == (352000.5, 6812000.25, "EPSG:2154")
    assert candidate.attributes["source_location_crs"] == "EPSG:4326"
    assert candidate.attributes["flow_station_influence_generale_site"] == "0"


@pytest.mark.parametrize("target", ["EPSG:2154", "EPSG:32630"])
def test_a_record_without_provider_coordinates_is_reprojected(target):
    record = make_point_record("J1", x=-1.65, y=48.12, crs="EPSG:4326")

    (candidate,) = candidate_outlets_from_point_records([record], target_crs=target)
    (same,) = candidate_outlets_from_point_records([record], target_crs="epsg:4326")

    assert candidate.crs == target
    assert candidate.x > 1000.0 and candidate.y > 1_000_000.0
    assert (same.x, same.y, same.crs) == (-1.65, 48.12, "EPSG:4326")


@pytest.mark.parametrize(
    ("crs", "coordinates", "expected"),
    [
        (
            "EPSG:2154",
            [("low", 0.0, 1.0), ("high", 500.0, 10.0), ("far", 5000.0, 0.0)],
            ["far", "high"],
        ),
        ("EPSG:4326", [("a", -1.0, 1.0), ("b", -1.001, 2.0)], ["b"]),
    ],
)
def test_thinning_keeps_the_highest_priority_of_close_outlets(crs, coordinates, expected):
    y = 48.0 if crs == "EPSG:4326" else 0.0
    candidates = [
        CandidateOutlet(name, x, y, crs, "test", priority=p) for name, x, p in coordinates
    ]

    selected = thin_candidate_outlets(candidates, min_distance_km=1.0)

    assert [one.candidate_id for one in selected] == expected


def test_thinning_refuses_a_null_distance_and_mixed_projections():
    candidates = [
        CandidateOutlet("a", 0.0, 0.0, "EPSG:2154", "test", priority=1.0),
        CandidateOutlet("b", 0.0, 0.0, "EPSG:32630", "test"),
    ]

    with pytest.raises(ValueError, match="must be > 0"):
        thin_candidate_outlets(candidates, min_distance_km=0.0)
    with pytest.raises(ValueError, match="different projected CRS"):
        thin_candidate_outlets(candidates, min_distance_km=1.0)
