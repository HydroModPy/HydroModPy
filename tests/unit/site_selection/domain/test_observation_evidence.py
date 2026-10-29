import pytest

from hydromodpy.spatial.site_selection.domain.observation_evidence import (
    ObservationEvidence,
    ObservationSpatialMatch,
)
from tests._helpers.site_selection_cases import make_point_record

pytestmark = pytest.mark.fast


def test_a_hubeau_record_keeps_its_provider_fields_apart_from_the_spatial_match():
    metadata = {
        "station_name": "La Riviere a Exemple",
        "department": "Ille-et-Vilaine",
        "influence_generale_site": "1",
        "commentaire_influence_generale_site": "Retenue en amont.",
    }
    record = make_point_record("J123456701", x=-1.5, y=48.1, crs="EPSG:4326", metadata=metadata)
    match = ObservationSpatialMatch(distance_to_outlet_km=0.25, distance_to_basin_km=0.0, inside_basin=True)  # fmt: skip

    evidence = ObservationEvidence.from_point_record(
        site_id="site_001", observation_type="flow_station", record=record, spatial_match=match,
        influence_status="unknown",
    )  # fmt: skip

    assert (evidence.source_dataset, evidence.feature_id) == ("hubeau", "J123456701")
    assert evidence.feature_label == "La Riviere a Exemple"
    assert (evidence.distance_to_outlet_km, evidence.inside_basin) == (0.25, True)
    assert evidence.influence_status == "general_influence"
    assert evidence.influence_flags == ["general_influence", "general_influence_comment_keyword"]
    assert evidence.upstream_dam_count is None
    payload = evidence.evidence_json
    assert payload["provider_metadata"]["department"] == "Ille-et-Vilaine"
    assert payload["station_influence"]["raw_fields"]["influence_generale_site"] == "1"
    assert payload["provider_location"]["crs"] == "EPSG:4326"
