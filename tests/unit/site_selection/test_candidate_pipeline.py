from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.spatial.site_selection.candidates.pipeline import (
    build_station_candidate_outlets,
    site_selection_search_geometry,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig


def _record(
    station_id: str,
    *,
    x: float,
    y: float,
    n_values: int,
) -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": [f"2020-01-{day:02d}" for day in range(1, n_values + 1)],
                "value": [float(day) for day in range(n_values)],
            }
        ),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, max(n_values, 1)),
        location=StationLocation(
            id=station_id,
            x=x,
            y=y,
            crs="EPSG:2154",
            metadata={"station_name": f"Station {station_id}"},
        ),
    )


def _config(tmp_path: Path, *, min_distance_km: float | None = None) -> SiteSelectionConfig:
    payload = {
        "selection_id": "candidate_pipeline",
        "output_root": tmp_path / "out",
        "strategy": {
            "principle": "observation_led",
            "profile": "gauged_downstream_station",
            "primary_observation_type": "flow_station",
            "candidate_mode": "station_outlets",
        },
        "territory": {
            "mode": "bbox",
            "country": "FR",
            "bbox": [0.0, 0.0, 10.0, 20.0],
        },
        "dem": {
            "source": "custom",
            "path": tmp_path / "dem.tif",
        },
        "outlets": {
            "candidate_mode": "station_outlets",
            "snap_dist_m": 150,
            "min_distance_between_outlets_km": min_distance_km,
        },
    }
    return SiteSelectionConfig.model_validate(payload)


@pytest.mark.fast
def test_build_station_candidate_outlets_applies_configured_thinning(tmp_path):
    candidates = build_station_candidate_outlets(
        [
            _record("A", x=0.0, y=0.0, n_values=5),
            _record("B", x=500.0, y=0.0, n_values=2),
            _record("C", x=2500.0, y=0.0, n_values=1),
        ],
        config=_config(tmp_path, min_distance_km=1.0),
        target_crs="EPSG:2154",
    )

    assert [candidate.source_feature_id for candidate in candidates] == ["A", "C"]


@pytest.mark.fast
def test_site_selection_search_geometry_returns_bbox_geometry(tmp_path):
    geometry = site_selection_search_geometry(
        _config(tmp_path),
        target_crs="EPSG:2154",
    )

    assert geometry is not None
    assert geometry.bounds == pytest.approx((0.0, 0.0, 10.0, 20.0))
