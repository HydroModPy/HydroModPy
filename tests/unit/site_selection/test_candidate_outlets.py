from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.site_selection.candidate_outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    candidate_outlets_from_rows,
    thin_candidate_outlets,
)


@pytest.mark.fast
def test_candidate_outlets_from_point_records_use_station_metadata():
    record = PointRecord(
        station_id="J123456701",
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01", "2020-01-02"], "value": [1.0, 2.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 2),
        location=StationLocation(
            id="J123456701",
            x=352000.0,
            y=6812000.0,
            crs="EPSG:2154",
            metadata={"station_name": "La Riviere a Exemple"},
        ),
    )

    candidates = candidate_outlets_from_point_records([record], candidate_prefix="station")

    assert len(candidates) == 1
    assert candidates[0].candidate_id == "station_J123456701"
    assert candidates[0].source_feature_id == "J123456701"
    assert candidates[0].source_label == "La Riviere a Exemple"
    assert candidates[0].priority == pytest.approx(2.0)


@pytest.mark.fast
def test_candidate_outlets_from_hubeau_records_use_lambert93_metadata_when_requested():
    record = PointRecord(
        station_id="J123456701",
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01"], "value": [1.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1),
        location=StationLocation(
            id="J123456701",
            x=-1.65,
            y=48.12,
            crs="EPSG:4326",
            metadata={
                "station_name": "Station HubEau",
                "x_l93": "352000.5",
                "y_l93": "6812000.25",
            },
        ),
    )

    candidates = candidate_outlets_from_point_records(
        [record],
        candidate_prefix="station",
        target_crs="EPSG:2154",
    )

    assert len(candidates) == 1
    assert candidates[0].x == pytest.approx(352000.5)
    assert candidates[0].y == pytest.approx(6812000.25)
    assert candidates[0].crs == "EPSG:2154"
    assert candidates[0].attributes["source_location_crs"] == "EPSG:4326"


@pytest.mark.fast
def test_candidate_outlets_from_rows_builds_imported_points():
    candidates = candidate_outlets_from_rows(
        [
            {"candidate_id": "a", "x": 1.0, "y": 2.0, "priority": 3.0},
            {"candidate_id": "b", "x": 3.0, "y": 4.0},
        ],
        source="manual",
    )

    assert [candidate.candidate_id for candidate in candidates] == ["manual_a", "manual_b"]
    assert candidates[0].priority == pytest.approx(3.0)
    assert candidates[1].crs == "EPSG:2154"


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
