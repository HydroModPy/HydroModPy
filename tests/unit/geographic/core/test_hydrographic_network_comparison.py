"""Two line networks compared within a tolerance: matched, missing and extra lengths."""

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point

from hydromodpy.spatial.geographic.core.hydrographic_network import HydrographicNetwork
from hydromodpy.spatial.geographic.core.hydrographic_network_comparison import (
    compare_hydrographic_networks,
)
from tests._helpers.geographic_cases import write_features

KM = LineString([(0.0, 0.0), (1000.0, 0.0)])


def _gdf(lines: list, crs: str = "EPSG:2154") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=lines, crs=crs)


CASES = {
    "exact match": (
        [KM],
        25.0,
        dict(candidate_total_length_m=1000.0, extra_candidate_length_m=0.0, length_f1_ratio=1.0),
    ),
    "missing and extra": (
        [LineString([(0, 0), (700, 0)]), LineString([(1000, 100), (1300, 100)])],
        0.0,
        {
            "matched_reference_length_m": 700.0,
            "matched_candidate_length_m": 700.0,
            "extra_candidate_length_m": 300.0,
            "reference_coverage_ratio": 0.7,
            "candidate_match_ratio": 0.7,
            "missing_reference_ratio": 0.3,
            "extra_candidate_ratio": 0.3,
        },
    ),
    "tolerance extends the ends": (
        [LineString([(0, 0), (700, 0)])],
        50.0,
        {"matched_reference_length_m": 750.0},
    ),
    "disjoint": ([LineString([(0, 500), (1000, 500)])], 10.0, {"length_f1_ratio": 0.0}),
    "collections and points": (
        [
            MultiLineString([[(0, 0), (400, 0)], [(400, 0), (1000, 0)]]),
            GeometryCollection([Point(5, 5), LineString([(0, 50), (100, 50)])]),
            Point(0, 0),
        ],
        10.0,
        {"matched_reference_length_m": 1000.0, "extra_candidate_length_m": 100.0},
    ),
    "empty candidate": (
        [],
        10.0,
        dict(matched_reference_length_m=0.0, candidate_match_ratio=None, length_f1_ratio=None),
    ),
}


@pytest.mark.parametrize(("candidate", "tolerance", "expected"), CASES.values(), ids=list(CASES))
def test_matched_plus_missing_is_the_reference_length(candidate, tolerance, expected) -> None:
    c = compare_hydrographic_networks(_gdf([KM]), _gdf(candidate), tolerance_m=tolerance)
    assert c.reference_total_length_m == pytest.approx(1000.0)
    assert c.matched_reference_length_m + c.missing_reference_length_m == pytest.approx(1000.0)
    assert c.matched_candidate_length_m + c.extra_candidate_length_m == pytest.approx(
        c.candidate_total_length_m
    )
    for name, value in expected.items():
        assert getattr(c, name) == (None if value is None else pytest.approx(value))
    record = c.to_metrics_record(case="x")
    assert (record["case"], record["reference_segment_count"]) == ("x", 1)


@pytest.mark.parametrize(
    ("candidate", "coverage"),
    [
        (_gdf([LineString([(0.0, 0.0), (0.008983, 0.0)])], crs="EPSG:4326"), 0.0),
        (_gdf([KM], crs="EPSG:4326"), 1.0),
    ],
    ids=["degrees", "metres labelled in degrees"],
)
def test_the_candidate_is_measured_in_the_crs_of_the_reference(candidate, coverage) -> None:
    comparison = compare_hydrographic_networks(_gdf([KM]), candidate, tolerance_m=100.0)
    assert "2154" in comparison.crs
    assert comparison.reference_coverage_ratio == pytest.approx(coverage)
    assert comparison.candidate_total_length_m > 0.0
    if coverage:
        assert comparison.candidate_total_length_m == pytest.approx(1000.0)
        assert comparison.candidate_match_ratio == pytest.approx(1.0)


def test_two_networks_of_the_contract_are_read_from_their_vectors(tmp_path) -> None:
    path = write_features(tmp_path / "streams.shp", [KM])
    reference = HydrographicNetwork(role="reference", source_kind="file", vector_path=path)
    comparison = compare_hydrographic_networks(reference, _gdf([KM]), tolerance_m=1.0)
    assert comparison.length_f1_ratio == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("reference", "error", "reason"),
    [
        (_gdf([KM]), ValueError, "tolerance"),
        (HydrographicNetwork(role="generated", source_kind="file"), ValueError, "no readable"),
        ([KM], TypeError, "HydrographicNetwork or a GeoDataFrame"),
    ],
    ids=["negative tolerance", "network without vector", "not a network"],
)
def test_a_comparison_that_cannot_be_measured_is_refused(reference, error, reason) -> None:
    tolerance = -1.0 if reason == "tolerance" else 1.0
    with pytest.raises(error, match=reason):
        compare_hydrographic_networks(reference, _gdf([KM]), tolerance_m=tolerance)
