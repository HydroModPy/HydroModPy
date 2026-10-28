"""Observation evidence from point records or from imported station attributes."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationSpatialMatch
from hydromodpy.spatial.site_selection.evidence.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from tests._helpers.site_selection_cases import make_point_record

pytestmark = pytest.mark.fast


def test_a_point_record_takes_the_spatial_match_of_its_station():
    record = make_point_record("A000000101", with_location=False)

    rows = build_observation_evidence(
        site_id="site_002",
        observation_type="flow_station",
        records=[record],
        spatial_matches={"A000000101": ObservationSpatialMatch(distance_to_outlet_km=1.2)},
    )

    assert [row.distance_to_outlet_km for row in rows] == [1.2]
    assert rows[0].to_record()["observation_type"] == "flow_station"


def test_imported_station_and_piezometer_attributes_become_two_evidences():
    attributes = {
        "flow_station_id": "J100000001",
        "flow_station_label": "Station fixture",
        "flow_station_x": "270150",
        "flow_station_y": "6815100",
        "flow_station_crs": "EPSG:2154",
        "flow_station_record_years": "n/a",
        "station_record_year_count": "9.0",
        "station_to_outlet_distance_km": "0.12",
        "flow_station_inside_basin": "maybe",
        "station_inside_or_at_outlet": "true",
        "flow_station_influence_locale_station": "1",
        "piezometer_id": "PZB0001",
        "piezometer_x": "266000",
        "piezometer_y": "6819000",
        "piezometer_distance_km": "1.8",
        "piezometer_inside_basin": "non",
    }

    flow, piezometer = build_observation_evidence_from_attributes(
        site_id="site_003", attributes=attributes
    )

    assert (flow.feature_id, flow.distance_to_outlet_km, flow.record_year_count) == (
        "J100000001", 0.12, 9.0,
    )  # fmt: skip
    assert (flow.inside_basin, flow.influence_status) == (True, "local_influence")
    assert flow.evidence_json["provider_location"]["crs"] == "EPSG:2154"
    assert (piezometer.feature_label, piezometer.source_dataset) == (
        "PZB0001",
        "imported_piezometry",
    )
    assert (piezometer.distance_to_outlet_km, piezometer.inside_basin) == (1.8, False)
    assert piezometer.evidence_json["provider_location"]["crs"] == ""
