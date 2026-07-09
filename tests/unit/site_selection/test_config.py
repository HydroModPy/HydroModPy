from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    CriteriaConfig,
    DemAreaTargetConfig,
    DemConfig,
    OutletsConfig,
    OutputConfig,
    SiteSelectionConfig,
    SiteSelectionInputConfig,
    SpatialSelectionConfig,
    StrategyConfig,
    TerritoryConfig,
)


@pytest.mark.fast
def test_area_only_config_keeps_observations_and_geology_report_only(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "area_only_demo",
            "output_root": tmp_path / "out",
            "strategy": {
                "profile": "area_only",
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
                    "flow_station_mode": "report_only",
                    "piezometer_mode": "report_only",
                },
                "geology": {"mode": "report_only"},
            },
        }
    )

    assert cfg.strategy.profile == "area_only"
    assert cfg.strategy.principle == "criteria_crossing"
    assert cfg.strategy.primary_axes == ["area"]
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
def test_removed_dem_source_data_alias_is_rejected():
    with pytest.raises(ValidationError):
        DemConfig.model_validate({"source": "data"})


@pytest.mark.fast
def test_dem_source_can_be_omitted_for_inference():
    cfg = DemConfig.model_validate({})

    assert cfg.source is None


@pytest.mark.fast
@pytest.mark.parametrize(
    "removed_field",
    [
        "request_extent",
        "extent_mode",
        "delineation_extent",
        "margin_km",
        "buffer_km",
        "map_background_extent",
    ],
)
def test_removed_dem_legacy_fields_are_rejected(removed_field):
    with pytest.raises(ValidationError, match=removed_field):
        DemConfig.model_validate({removed_field: "outlets"})


@pytest.mark.fast
def test_hydrology_removed_method_is_rejected():
    with pytest.raises(ValidationError, match="method"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "removed_hydrology_method",
                "output_root": "out",
                "hydrology": {"method": "dem_only"},
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretagne"],
                },
            }
        )


@pytest.mark.fast
def test_region_id_is_inferred_from_single_admin_region(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "region_label_demo",
            "output_root": tmp_path / "out",
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.input.region_id == "Bretagne"
    assert cfg.resolved_region_id == "Bretagne"


@pytest.mark.fast
def test_region_id_override_wins_over_territory_inference(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "region_label_override",
            "output_root": tmp_path / "out",
            "input": {"region_id": "AURA campaign"},
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Auvergne-Rhone-Alpes"],
            },
        }
    )

    assert cfg.input.region_id == "AURA campaign"
    assert cfg.resolved_region_id == "AURA campaign"


@pytest.mark.fast
def test_region_id_is_not_inferred_from_multiple_regions(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "multi_region_label_demo",
            "output_root": tmp_path / "out",
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne", "Normandie"],
            },
        }
    )

    assert cfg.input.region_id == ""
    assert cfg.resolved_region_id == ""


@pytest.mark.fast
def test_criteria_ruleset_is_inferred_from_selection_id(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "derived_ruleset_demo",
            "output_root": tmp_path / "out",
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.criteria.ruleset == "derived_ruleset_demo"


@pytest.mark.fast
def test_explicit_criteria_ruleset_is_preserved_and_trimmed(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "derived_ruleset_demo",
            "output_root": tmp_path / "out",
            "criteria": {"ruleset": " shared_rules_v1 "},
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.criteria.ruleset == "shared_rules_v1"


@pytest.mark.fast
def test_area_only_rejects_observation_bonus():
    with pytest.raises(ValueError, match="area_only requires observation_role"):
        StrategyConfig(
            profile="area_only",
            observation_role="bonus",
        )


@pytest.mark.fast
def test_gauged_profile_infers_observation_led_defaults(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "observed",
            "output_root": tmp_path / "out",
            "strategy": {"profile": "gauged_downstream_station"},
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.strategy.principle == "observation_led"
    assert cfg.strategy.primary_observation_type == "flow_station"
    assert cfg.strategy.candidate_mode == "station_outlets"
    assert cfg.outlets.candidate_mode == "station_outlets"


@pytest.mark.fast
def test_hydrometry_mode_infers_gauged_downstream_station_profile(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "observed",
            "output_root": tmp_path / "out",
            "input": {"mode": "hydrometry"},
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.strategy.profile == "gauged_downstream_station"
    assert cfg.effective_profile == "gauged_downstream_station"
    assert cfg.strategy.principle == "observation_led"
    assert cfg.strategy.primary_observation_type == "flow_station"
    assert cfg.strategy.candidate_mode == "station_outlets"
    assert cfg.outlets.candidate_mode == "station_outlets"


@pytest.mark.fast
def test_hydrometry_mode_rejects_contradictory_profile(tmp_path):
    with pytest.raises(ValueError, match="mode='hydrometry'.*profile"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "observed",
                "output_root": tmp_path / "out",
                "input": {"mode": "hydrometry"},
                "strategy": {"profile": "area_only"},
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretagne"],
                },
            }
        )


@pytest.mark.fast
def test_observation_led_requires_explicit_gauged_profile(tmp_path):
    with pytest.raises(ValueError, match="profile='gauged_downstream_station'"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "observed",
                "output_root": tmp_path / "out",
                "strategy": {
                    "principle": "observation_led",
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
                "profile": "gauged_downstream_station",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.strategy.principle == "observation_led"
    assert cfg.effective_profile == "gauged_downstream_station"


@pytest.mark.fast
def test_gauged_downstream_station_profile_can_still_be_declared_explicitly(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "gauged",
            "output_root": tmp_path / "out",
            "strategy": {
                "profile": "gauged_downstream_station",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
        }
    )

    assert cfg.strategy.profile == "gauged_downstream_station"
    assert cfg.effective_profile == "gauged_downstream_station"
    assert cfg.strategy.principle == "observation_led"
    assert cfg.strategy.primary_observation_type == "flow_station"
    assert cfg.strategy.candidate_mode == "station_outlets"


@pytest.mark.fast
def test_gauged_downstream_station_rejects_explicit_network_sampling(tmp_path):
    with pytest.raises(ValueError, match="candidate_mode='station_outlets'"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "gauged",
                "output_root": tmp_path / "out",
                "strategy": {
                    "profile": "gauged_downstream_station",
                },
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretagne"],
                },
                "outlets": {
                    "candidate_mode": "network_sampling",
                },
            }
        )


@pytest.mark.fast
def test_gauged_downstream_station_profile_requires_flow_station(tmp_path):
    with pytest.raises(ValueError, match="primary_observation_type='flow_station'"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "gauged",
                "output_root": tmp_path / "out",
                "strategy": {
                    "profile": "gauged_downstream_station",
                    "primary_observation_type": "piezometer",
                },
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Bretagne"],
                },
                "outlets": {
                    "candidate_mode": "station_outlets",
                },
            }
        )


@pytest.mark.fast
def test_criterion_mode_rejects_legacy_report_alias():
    with pytest.raises(ValueError, match="report_only"):
        AreaCriteriaConfig(mode="report")


@pytest.mark.fast
def test_removed_candidate_modes_are_rejected():
    with pytest.raises(ValueError, match="imported_points"):
        OutletsConfig(candidate_mode="imported_points")


@pytest.mark.fast
def test_removed_territory_modes_are_rejected():
    with pytest.raises(ValueError, match="site_catalog_extent"):
        TerritoryConfig(mode="site_catalog_extent")


@pytest.mark.fast
def test_removed_spatial_policy_is_rejected():
    with pytest.raises(ValueError, match="same_mainstem_policy"):
        SpatialSelectionConfig(same_mainstem_policy="keep_best")


@pytest.mark.fast
def test_removed_output_switches_are_rejected():
    with pytest.raises(ValueError, match="write_candidates"):
        OutputConfig(write_candidates=False)

    with pytest.raises(ValueError, match="write_report_md"):
        OutputConfig(write_report_md=False)

    with pytest.raises(ValueError, match="write_report_html"):
        OutputConfig(write_report_html=True)


@pytest.mark.fast
def test_removed_criteria_soft_score_alias_is_rejected():
    with pytest.raises(ValueError, match="soft_score"):
        CriteriaConfig.model_validate({"soft_score": ["record_length"]})


@pytest.mark.fast
def test_auto_input_mode_is_rejected():
    with pytest.raises(ValueError, match="auto"):
        SiteSelectionInputConfig(mode="auto")


@pytest.mark.fast
def test_plan_only_input_mode_is_migrated_to_dry_run():
    cfg = SiteSelectionInputConfig(mode="plan_only")

    assert cfg.mode == "dry_run"


@pytest.mark.fast
def test_outlet_snap_strategy_accepts_bdtopage_then_dem():
    cfg = OutletsConfig(
        candidate_mode="station_outlets",
        snap_strategy="bdtopage_then_dem",
        dem_snap_max_distance_m=150,
        reference_network_snap_max_distance_m=75.0,
    )

    assert cfg.snap_strategy == "bdtopage_then_dem"
    assert cfg.dem_snap_max_distance_m == 150
    assert cfg.reference_network_source == "bdtopage"
    assert cfg.reference_network_snap_max_distance_m == pytest.approx(75.0)


@pytest.mark.fast
def test_removed_outlet_snap_aliases_are_rejected():
    with pytest.raises(ValidationError, match="snap_dist_m"):
        OutletsConfig.model_validate({"snap_dist_m": 150})

    with pytest.raises(ValidationError, match="reference_network_snap_tolerance_m"):
        OutletsConfig.model_validate({"reference_network_snap_tolerance_m": 75.0})


@pytest.mark.fast
def test_removed_reference_network_distance_alias_is_rejected():
    with pytest.raises(ValidationError, match="reference_network_max_distance_m"):
        OutletsConfig.model_validate(
            {
                "snap_strategy": "bdtopage_then_dem",
                "reference_network_max_distance_m": 75.0,
            }
        )


@pytest.mark.fast
def test_custom_reference_network_requires_path():
    with pytest.raises(ValueError, match="requires reference_network_path"):
        OutletsConfig(
            snap_strategy="bdtopage_then_dem",
            reference_network_source="custom",
        )


@pytest.mark.fast
def test_grid_spatial_quota_requires_cell_size():
    with pytest.raises(ValueError, match="spatial_quota_cell_size_km"):
        SpatialSelectionConfig(spatial_quota_mode="grid")


@pytest.mark.fast
def test_area_hard_bounds_must_be_ordered():
    with pytest.raises(ValueError, match="hard_min_area_km2"):
        AreaCriteriaConfig(
            mode="hard_reject",
            hard_min_area_km2=200.0,
            hard_max_area_km2=100.0,
        )


@pytest.mark.fast
def test_dem_area_target_config_defaults_to_100_km2_window(tmp_path):
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "dem_area_target",
            "output_root": tmp_path / "out",
            "input": {"mode": "dem_area_target"},
            "strategy": {
                "profile": "area_only",
                "observation_role": "report_only",
                "geology_role": "report_only",
            },
            "criteria": {
                "area": {
                    "mode": "hard_reject",
                    "hard_min_area_km2": 75.0,
                    "hard_max_area_km2": 125.0,
                },
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Normandie"],
            },
        }
    )

    assert cfg.dem_area_target is not None
    assert cfg.dem_area_target.target_area_km2 == pytest.approx(100.0)
    assert cfg.dem_area_target.min_area_km2 == pytest.approx(75.0)
    assert cfg.dem_area_target.max_area_km2 == pytest.approx(125.0)
    assert cfg.dem_area_target.n_basins == 50
    assert cfg.dem_area_target.max_candidates_before_delineation is None


@pytest.mark.fast
def test_dem_area_target_requires_explicit_area_only_profile(tmp_path):
    with pytest.raises(ValueError, match="strategy.profile='area_only'"):
        SiteSelectionConfig.model_validate(
            {
                "selection_id": "dem_area_target",
                "output_root": tmp_path / "out",
                "input": {"mode": "dem_area_target"},
                "territory": {
                    "mode": "admin_regions",
                    "country": "FR",
                    "regions": ["Normandie"],
                },
            }
        )


@pytest.mark.fast
def test_dem_area_target_target_must_be_inside_window():
    with pytest.raises(ValueError, match="target_area_km2"):
        DemAreaTargetConfig(
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
