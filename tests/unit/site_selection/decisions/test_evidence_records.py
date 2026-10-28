"""Observation, influence and geology evidence become normalized evidence records."""

from __future__ import annotations

import json

import pytest
from shapely.geometry import Point, box

from hydromodpy.spatial.site_selection.decisions.evidence_records import (
    evidence_records_from_site_selection_evidence,
)
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.outputs.decision_files import write_evidence_records_jsonl

pytestmark = pytest.mark.fast


def _observation(feature_id: str, x: object = 350000.0) -> ObservationEvidence:
    location = {"x": x, "y": 6810000.0, "crs": "EPSG:2154"}
    return ObservationEvidence(
        site_id="site_001",
        observation_type="flow_station",
        source_dataset="hubeau",
        feature_id=feature_id,
        evidence_json={"provider_location": location},
    )


def _geology(geology_class: str) -> GeologyEvidence:
    return GeologyEvidence(
        site_id="site_001",
        source_layer="BRGM demo",
        geology_class=geology_class,
        area_fraction=0.7,
        area_km2=70.0,
        feature_count=1,
        feature_ids=["G001"],
        geometry=box(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )


def test_evidence_without_an_identifier_is_left_out_and_the_rest_is_written(tmp_path):
    influence = InfluenceEvidence(
        site_id="site_001",
        influence_type="major_dam_upstream",
        source_layer="ROE demo",
        feature_id="DAM001",
        geometry=Point(350010.0, 6810010.0),
        crs="EPSG:2154",
    )

    records = evidence_records_from_site_selection_evidence(
        run_id="run_v1",
        observation_evidence=[_observation("J001001001"), _observation("J2", "east"), _observation("")],
        influence_evidence=[influence],
        geology_evidence=[_geology("schist"), _geology("")],
    )  # fmt: skip

    refs = {record.evidence_ref: record for record in records}
    assert set(refs) == {
        "flow_station:site_001:J001001001",
        "flow_station:site_001:J2",
        "influence:site_001:major_dam_upstream:DAM001",
        "geology:site_001:BRGM demo:schist",
    }
    flow = refs["flow_station:site_001:J001001001"]
    assert flow.geometry == {"type": "Point", "coordinates": [350000.0, 6810000.0]}
    assert flow.properties["provider_location_crs"] == "EPSG:2154"
    assert refs["flow_station:site_001:J2"].geometry is None
    assert refs["geology:site_001:BRGM demo:schist"].feature_id == "G001"

    path = write_evidence_records_jsonl(tmp_path / "site_selection_evidence.jsonl", records)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {line["evidence_ref"] for line in lines} == set(refs)
    assert {line["geometry"]["type"] for line in lines if line["geometry"]} == {"Point", "Polygon"}
