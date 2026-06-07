from __future__ import annotations

import json

import pytest
from shapely.geometry import Point, Polygon

from hydromodpy.spatial.site_selection.decisions import (
    evidence_records_from_site_selection_evidence,
    write_evidence_records_jsonl,
)
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.context import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence


@pytest.mark.fast
def test_evidence_records_normalize_observation_influence_and_geology(tmp_path):
    observation = ObservationEvidence(
        site_id="site_001",
        observation_type="flow_station",
        source_dataset="hubeau",
        feature_id="J001001001",
        feature_label="Station demo",
        evidence_json={
            "provider_location": {
                "x": 350000.0,
                "y": 6810000.0,
                "crs": "EPSG:2154",
            }
        },
    )
    influence = InfluenceEvidence(
        site_id="site_001",
        influence_type="major_dam_upstream",
        source_layer="ROE demo",
        feature_id="DAM001",
        feature_label="Dam demo",
        geometry=Point(350010.0, 6810010.0),
        crs="EPSG:2154",
    )
    geology = GeologyEvidence(
        site_id="site_001",
        source_layer="BRGM demo",
        geology_class="schist",
        area_fraction=0.7,
        area_km2=70.0,
        feature_count=1,
        feature_ids=["G001"],
        geometry=Polygon(
            [
                (0.0, 0.0),
                (1.0, 0.0),
                (1.0, 1.0),
                (0.0, 1.0),
                (0.0, 0.0),
            ]
        ),
        crs="EPSG:2154",
    )

    records = evidence_records_from_site_selection_evidence(
        run_id="run_v1",
        observation_evidence=[observation],
        influence_evidence=[influence],
        geology_evidence=[geology],
    )

    refs = {record.evidence_ref for record in records}
    assert refs == {
        "flow_station:site_001:J001001001",
        "influence:site_001:major_dam_upstream:DAM001",
        "geology:site_001:BRGM demo:schist",
    }
    flow = next(record for record in records if record.criterion_id == "flow_station")
    assert flow.geometry == {"type": "Point", "coordinates": [350000.0, 6810000.0]}
    assert flow.properties["provider_location_crs"] == "EPSG:2154"

    path = write_evidence_records_jsonl(tmp_path / "site_selection_evidence.jsonl", records)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {line["evidence_ref"] for line in lines} == refs
    assert any(line["geometry"]["type"] == "Point" for line in lines)
