from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    SiteSelectionConfig,
    StrategyConfig,
)


@pytest.mark.fast
def test_area_only_config_keeps_observations_and_geology_report_only(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "area_only_demo",
            "output_root": tmp_path / "out",
            "strategy": {
                "principle": "criteria_crossing",
                "profile": "area_only",
                "primary_axes": ["area"],
                "observation_role": "report_only",
                "geology_role": "report_only",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Auvergne-Rhone-Alpes"],
            },
            "criteria": {
                "area": {
                    "mode": "hard_reject",
                    "target_area_km2": 100.0,
                    "hard_min_area_km2": 75.0,
                    "hard_max_area_km2": 125.0,
                },
                "observations": {
                    "flow_station_mode": "report",
                    "piezometer_mode": "report",
                },
                "geology": {"mode": "report"},
            },
        }
    )

    assert cfg.strategy.profile == "area_only"
    assert cfg.criteria.observations.flow_station_mode == "report_only"
    assert cfg.criteria.geology.mode == "report_only"
    assert cfg.criteria.area.hard_min_area_km2 == pytest.approx(75.0)


@pytest.mark.fast
def test_french_admin_region_is_validated_and_canonicalized(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "region_alias_demo",
            "output_root": tmp_path / "out",
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["La Reunion"],
            },
        }
    )

    assert cfg.territory.regions == ["La-Reunion"]


@pytest.mark.fast
def test_french_admin_region_rejects_unknown_name(tmp_path):
    with pytest.raises(ValueError, match="Unknown French region"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "bad_region_demo",
                "output_root": tmp_path / "out",
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretange"],
                },
            }
        )


@pytest.mark.fast
def test_area_only_rejects_observation_bonus():
    with pytest.raises(ValueError, match="area_only requires observation_role"):
        StrategyConfig(
            principle="criteria_crossing",
            profile="area_only",
            primary_axes=["area"],
            observation_role="bonus",
        )


@pytest.mark.fast
def test_observation_led_requires_station_candidate_mode(tmp_path):
    with pytest.raises(ValueError, match="candidate_mode='station_outlets'"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "observed",
                "output_root": tmp_path / "out",
                "strategy": {
                    "principle": "observation_led",
                    "primary_observation_type": "flow_station",
                },
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretagne"],
                },
            }
        )


@pytest.mark.fast
def test_observation_led_accepts_station_outlets(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "observed",
            "output_root": tmp_path / "out",
            "strategy": {
                "principle": "observation_led",
                "primary_observation_type": "flow_station",
                "candidate_mode": "station_outlets",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.strategy.principle == "observation_led"


@pytest.mark.fast
def test_area_hard_bounds_must_be_ordered():
    with pytest.raises(ValueError, match="hard_min_area_km2"):
        AreaCriteriaConfig(
            mode="hard_reject",
            hard_min_area_km2=200.0,
            hard_max_area_km2=100.0,
        )


@pytest.mark.fast
def test_area_ranges_must_have_ordered_min_max():
    with pytest.raises(ValueError, match="min_area_km2"):
        AreaCriteriaConfig.model_validate(
            {
                "mode": "hard_reject",
                "ranges": [
                    {
                        "range_id": "bad",
                        "min_area_km2": 150.0,
                        "max_area_km2": 50.0,
                    }
                ],
            }
        )
