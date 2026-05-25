from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    DemAreaLightConfig,
    OutletsConfig,
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
def test_outlet_snap_strategy_accepts_bdtopage_then_dem():
    cfg = OutletsConfig(
        candidate_mode="station_outlets",
        snap_strategy="bdtopage_then_dem",
        snap_dist_m=150,
        reference_network_max_distance_m=75.0,
    )

    assert cfg.snap_strategy == "bdtopage_then_dem"
    assert cfg.snap_dist_m == 150
    assert cfg.reference_network_source == "bdtopage"


@pytest.mark.fast
def test_custom_reference_network_requires_path():
    with pytest.raises(ValueError, match="requires reference_network_path"):
        OutletsConfig(
            snap_strategy="bdtopage_then_dem",
            reference_network_source="custom",
        )


@pytest.mark.fast
def test_area_hard_bounds_must_be_ordered():
    with pytest.raises(ValueError, match="hard_min_area_km2"):
        AreaCriteriaConfig(
            mode="hard_reject",
            hard_min_area_km2=200.0,
            hard_max_area_km2=100.0,
        )


@pytest.mark.fast
def test_dem_area_light_config_defaults_to_100_km2_window(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "dem_area_light",
            "output_root": tmp_path / "out",
            "input": {"mode": "dem_area_light"},
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Normandie"],
            },
        }
    )

    assert cfg.dem_area_light is not None
    assert cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert cfg.dem_area_light.min_area_km2 == pytest.approx(75.0)
    assert cfg.dem_area_light.max_area_km2 == pytest.approx(125.0)
    assert cfg.dem_area_light.n_basins == 50
    assert cfg.dem_area_light.max_candidates_before_delineation is None


@pytest.mark.fast
def test_dem_area_light_target_must_be_inside_window():
    with pytest.raises(ValueError, match="target_area_km2"):
        DemAreaLightConfig(
            target_area_km2=50.0,
            min_area_km2=75.0,
            max_area_km2=125.0,
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
