"""Site-selection keys no step read are refused with the key that does the job.

Each of them was written to the manifest or the evidence and changed nothing,
or did the job of another key that wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.spatial.site_selection.config.models import SiteSelectionConfig


def _payload(tmp_path: Path, **sections: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "selection_id": "refusals",
        "output_root": tmp_path / "out",
        "territory": {"mode": "bbox", "country": "FR", "bbox": [0.0, 0.0, 10.0, 10.0]},
    }
    payload.update(sections)
    return payload


@pytest.mark.fast
@pytest.mark.parametrize(
    ("sections", "key", "advice"),
    [
        ({"random_seed": 7}, "random_seed", "Remove the key"),
        ({"dem": {"resolution_m": 25.0}}, "resolution_m", "[data.dem]"),
        ({"dem": {"cache_policy": "use_cache_else_download"}}, "cache_policy", "force_refresh"),
        ({"criteria": {"ruleset": "v1"}}, "ruleset", "Remove the key"),
        ({"criteria": {"hard_reject": ["area_range"]}}, "hard_reject", "criteria.area.mode"),
        ({"criteria": {"warning": ["geology"]}}, "warning", "criteria.geology.mode"),
        ({"criteria": {"soft_score": ["record_length"]}}, "soft_score", "own mode"),
        ({"criteria": {"report_only": ["piezometry"]}}, "report_only", "piezometer_mode"),
        (
            {"criteria": {"geology": {"prefer_diversity": True}}},
            "prefer_diversity",
            "geology.mode = 'stratify'",
        ),
        (
            {"strategy": {"candidate_mode": "station_outlets"}},
            "candidate_mode",
            "site_selection.outlets.candidate_mode",
        ),
        (
            {"criteria": {"observations": {"flow_station_mode": "hard_reject"}}},
            "flow_station_mode",
            "[site_selection.criteria.observations.flow_station]",
        ),
        (
            {"criteria": {"observations": {"flow_station_max_distance_km": 1.0}}},
            "flow_station_max_distance_km",
            "max_station_to_outlet_distance_km",
        ),
    ],
)
def test_an_unread_key_is_refused_with_what_to_write(
    tmp_path: Path, sections: dict[str, object], key: str, advice: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        SiteSelectionConfig.model_validate(_payload(tmp_path, **sections))
    message = str(excinfo.value)
    assert f"'{key}' is not accepted any more" in message
    assert advice in message


@pytest.mark.fast
def test_the_flow_station_table_holds_its_mode_and_distance(tmp_path: Path) -> None:
    cfg = SiteSelectionConfig.model_validate(
        _payload(
            tmp_path,
            criteria={
                "observations": {
                    "flow_station": {
                        "mode": "hard_reject",
                        "max_station_to_outlet_distance_km": 2.0,
                    }
                }
            },
        )
    )
    flow_station = cfg.criteria.observations.flow_station
    assert flow_station.mode == "hard_reject"
    assert flow_station.max_station_to_outlet_distance_km == pytest.approx(2.0)


@pytest.mark.fast
def test_the_lake_abacus_id_is_refused_with_lake_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as excinfo:
        LakeAbacusConfig(sources=[{"path": tmp_path / "abacus.csv"}], id="lac0_abacus")
    message = str(excinfo.value)
    assert "'id' is not accepted any more" in message
    assert "lake_id" in message
