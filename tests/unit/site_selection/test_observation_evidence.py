from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.site_selection.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from hydromodpy.spatial.site_selection.types import (
    ObservationEvidence,
    ObservationSpatialMatch,
)


@pytest.mark.fast
def test_observation_evidence_from_hubeau_point_record_separates_provider_and_spatial_fields():
    record = PointRecord(
        station_id="J123456701",
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", "2020-01-10", freq="D"),
                "value": [1.0] * 10,
            }
        ),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 10),
        location=StationLocation(
            id="J123456701",
            x=-1.5,
            y=48.1,
            crs="EPSG:4326",
            metadata={
                "station_name": "La Riviere a Exemple",
                "city": "Exemple",
                "department": "Ille-et-Vilaine",
            },
        ),
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
    assert evidence.influence_status == "unknown"
    assert evidence.upstream_dam_count is None
    assert evidence.evidence_json["provider_metadata"]["department"] == "Ille-et-Vilaine"
    assert evidence.evidence_json["provider_location"]["crs"] == "EPSG:4326"


@pytest.mark.fast
def test_build_observation_evidence_uses_station_spatial_match():
    record = PointRecord(
        station_id="A000000101",
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01"], "value": [1.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1),
    )

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
    assert flow.evidence_json["provider_location"]["crs"] == "EPSG:2154"
