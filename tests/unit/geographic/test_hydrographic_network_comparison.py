from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.hydrographic_network_comparison import (
    compare_hydrographic_networks,
)


def _gdf(lines: list[LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=lines, crs="EPSG:2154")


def test_compare_hydrographic_networks_exact_match():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])

    comparison = compare_hydrographic_networks(reference, candidate, tolerance_m=25.0)

    assert comparison.reference_total_length_m == pytest.approx(1000.0)
    assert comparison.candidate_total_length_m == pytest.approx(1000.0)
    assert comparison.reference_coverage_ratio == pytest.approx(1.0)
    assert comparison.candidate_match_ratio == pytest.approx(1.0)
    assert comparison.missing_reference_length_m == pytest.approx(0.0)
    assert comparison.extra_candidate_length_m == pytest.approx(0.0)
    assert comparison.length_f1_ratio == pytest.approx(1.0)


def test_compare_hydrographic_networks_reports_missing_and_extra_segments():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = _gdf(
        [
            LineString([(0.0, 0.0), (700.0, 0.0)]),
            LineString([(1000.0, 100.0), (1300.0, 100.0)]),
        ]
    )

    comparison = compare_hydrographic_networks(reference, candidate, tolerance_m=0.0)

    assert comparison.matched_reference_length_m == pytest.approx(700.0)
    assert comparison.missing_reference_length_m == pytest.approx(300.0)
    assert comparison.matched_candidate_length_m == pytest.approx(700.0)
    assert comparison.extra_candidate_length_m == pytest.approx(300.0)
    assert comparison.reference_coverage_ratio == pytest.approx(0.7)
    assert comparison.candidate_match_ratio == pytest.approx(0.7)
    assert comparison.missing_reference_ratio == pytest.approx(0.3)
    assert comparison.extra_candidate_ratio == pytest.approx(0.3)
    assert comparison.reference_missing_gdf.empty is False
    assert comparison.candidate_extra_gdf.empty is False


def test_compare_hydrographic_networks_tolerance_extends_match_at_segment_ends():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = _gdf([LineString([(0.0, 0.0), (700.0, 0.0)])])

    comparison = compare_hydrographic_networks(reference, candidate, tolerance_m=50.0)

    assert comparison.matched_reference_length_m == pytest.approx(750.0)
    assert comparison.missing_reference_length_m == pytest.approx(250.0)


def test_compare_hydrographic_networks_reprojects_candidate_to_reference_crs():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = gpd.GeoDataFrame(
        geometry=[LineString([(0.0, 0.0), (0.008983, 0.0)])],
        crs="EPSG:4326",
    )

    comparison = compare_hydrographic_networks(reference, candidate, tolerance_m=100.0)

    assert comparison.crs is not None
    assert "2154" in comparison.crs
    assert comparison.reference_coverage_ratio is not None


def test_compare_hydrographic_networks_recovers_from_invalid_geographic_label():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = gpd.GeoDataFrame(
        geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
        crs="EPSG:4326",
    )

    comparison = compare_hydrographic_networks(reference, candidate, tolerance_m=10.0)

    assert comparison.crs is not None
    assert "2154" in comparison.crs
    assert comparison.reference_total_length_m == pytest.approx(1000.0)
    assert comparison.candidate_total_length_m == pytest.approx(1000.0)
    assert comparison.reference_coverage_ratio == pytest.approx(1.0)
    assert comparison.candidate_match_ratio == pytest.approx(1.0)


def test_compare_hydrographic_networks_rejects_negative_tolerance():
    reference = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])
    candidate = _gdf([LineString([(0.0, 0.0), (1000.0, 0.0)])])

    with pytest.raises(ValueError):
        compare_hydrographic_networks(reference, candidate, tolerance_m=-1.0)
