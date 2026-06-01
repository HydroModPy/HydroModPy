from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.domain.observations import (
    ObservationEvidence,
    ObservationSpatialMatch,
)
from hydromodpy.spatial.site_selection.evidence.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from tests.unit.site_selection._records import make_point_record


@pytest.mark.fast
def test_observation_evidence_from_hubeau_point_record_separates_provider_and_spatial_fields():
    record = make_point_record(
        "J123456701",
        x=-1.5,
        y=48.1,
        crs="EPSG:4326",
        n_values=10,
        metadata={
            "station_name": "La Riviere a Exemple",
            "city": "Exemple",
            "department": "Ille-et-Vilaine",
            "influence_generale_site": "1",
            "commentaire_influence_generale_site": "Retenue en amont.",
        },
    )
    match = ObservationSpatialMatch(
        distance_to_outlet_km=0.25,
        distance_to_basin_km=0.0,
        inside_basin=True,
    )

    evidence = ObservationEvidence.from_point_record(
        site_id="site_001",
        observation_type="flow_station",
        record=record,
        spatial_match=match,
        influence_status="unknown",
    )

    assert evidence.source_dataset == "hubeau"
    assert evidence.feature_id == "J123456701"
    assert evidence.feature_label == "La Riviere a Exemple"
    assert evidence.distance_to_outlet_km == pytest.approx(0.25)
    assert evidence.inside_basin is True
    assert evidence.influence_status == "general_influence"
    assert evidence.influence_flags == [
        "general_influence",
        "general_influence_comment_keyword",
    ]
    assert evidence.upstream_dam_count is None
    assert evidence.evidence_json["provider_metadata"]["department"] == "Ille-et-Vilaine"
    assert (
        evidence.evidence_json["station_influence"]["raw_fields"]["influence_generale_site"] == "1"
    )
    assert evidence.evidence_json["provider_location"]["crs"] == "EPSG:4326"


@pytest.mark.fast
def test_build_observation_evidence_uses_station_spatial_match():
    record = make_point_record("A000000101", with_location=False)

    rows = build_observation_evidence(
        site_id="site_002",
        observation_type="flow_station",
        records=[record],
        spatial_matches={
            "A000000101": ObservationSpatialMatch(distance_to_outlet_km=1.2),
        },
    )

    assert len(rows) == 1
    assert rows[0].distance_to_outlet_km == pytest.approx(1.2)
    assert rows[0].to_record()["observation_type"] == "flow_station"


@pytest.mark.fast
def test_build_observation_evidence_from_attributes_supports_imported_station_points():
    rows = build_observation_evidence_from_attributes(
        site_id="site_003",
        attributes={
            "flow_station_id": "J100000001",
            "flow_station_label": "Station fixture",
            "flow_station_x": "270150",
            "flow_station_y": "6815100",
            "flow_station_crs": "EPSG:2154",
            "flow_station_record_years": "9.0",
            "station_to_outlet_distance_km": "0.12",
            "station_inside_or_at_outlet": "true",
            "flow_station_influence_locale_station": "1",
            "piezometer_id": "PZB0001",
            "piezometer_label": "Piezometre fixture",
            "piezometer_x": "266000",
            "piezometer_y": "6819000",
            "piezometer_crs": "EPSG:2154",
            "piezometer_distance_km": "1.8",
        },
    )

    assert {row.observation_type for row in rows} == {"flow_station", "piezometer"}
    flow = next(row for row in rows if row.observation_type == "flow_station")
    assert flow.feature_id == "J100000001"
    assert flow.distance_to_outlet_km == pytest.approx(0.12)
    assert flow.inside_basin is True
    assert flow.influence_status == "local_influence"
    assert flow.evidence_json["provider_location"]["crs"] == "EPSG:2154"
