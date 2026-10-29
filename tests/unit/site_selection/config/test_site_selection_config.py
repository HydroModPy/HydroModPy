from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.spatial.site_selection.config.criteria_config import (
    AreaCriteriaConfig,
    AreaRangeConfig,
)
from hydromodpy.spatial.site_selection.config.dem_config import DemAreaLightConfig
from hydromodpy.spatial.site_selection.config.outlets_config import (
    OutletsConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.config.site_selection_config import (
    OutputConfig,
    SiteSelectionConfig,
    SiteSelectionInputConfig,
)
from hydromodpy.spatial.site_selection.config.strategy_config import StrategyConfig, TerritoryConfig
from hydromodpy.spatial.site_selection.config.value_types import (
    CandidateMode,
    StrategyProfile,
    WorkflowInputMode,
)
from hydromodpy.spatial.terrain import registry
from tests._helpers.site_selection_cases import make_config, selection_section

pytestmark = pytest.mark.fast


def _config(tmp_path: Path, profile: str = "area_only", **tables) -> SiteSelectionConfig:
    payload = selection_section(profile, output_root=tmp_path / "out", **tables)
    return SiteSelectionConfig.model_validate(payload)


def test_each_profile_sets_its_strategy_and_area_only_keeps_the_rest_report_only(tmp_path):
    ranges = [{"range_id": "mid", "min_area_km2": 50.0, "max_area_km2": 150.0}]
    area = {"mode": "hard_reject", "ranges": ranges}
    cfg = _config(tmp_path, territory={"regions": ["La Reunion"]}, criteria={"area": area})
    assert cfg.effective_profile == "area_only"
    assert cfg.criteria.observations.flow_station.mode == "report_only"
    assert cfg.criteria.geology.mode == "report_only"
    assert cfg.territory.regions == ["La-Reunion"]
    assert cfg.criteria.area.ranges[0].range_id == "mid"
    assert _config(tmp_path, "custom").effective_profile == "custom"
    gauged = _config(tmp_path, "gauged")
    assert (gauged.strategy.principle, gauged.effective_profile) == ("observation_led", "gauged_downstream_station")  # fmt: skip


def test_the_dem_window_defaults_to_100_km2_and_the_bdtopage_snap_to_bdtopage(tmp_path):
    cfg = _config(tmp_path, input={"mode": "dem_area_light"})
    assert cfg.dem_area_light == DemAreaLightConfig()
    assert (cfg.dem_area_light.min_area_km2, cfg.dem_area_light.max_area_km2) == (75.0, 125.0)
    assert cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    outlets = OutletsConfig(snap_strategy="bdtopage_then_dem", snap_dist_m=150)
    assert outlets.reference_network_source == "bdtopage"


def test_removed_legacy_literals_stay_removed():
    assert "auto" not in get_args(WorkflowInputMode)
    assert {"dem_only", "multicriteria"}.isdisjoint(get_args(StrategyProfile))
    assert {"dem_area_light", "imported_points"}.isdisjoint(get_args(CandidateMode))
    assert "same_mainstem_policy" not in SpatialSelectionConfig.model_fields
    assert {"write_candidates", "write_report_md"}.isdisjoint(OutputConfig.model_fields)


AREA_ONLY = {"principle": "criteria_crossing", "profile": "area_only", "primary_axes": ["area"]}
GAUGED = {"principle": "observation_led", "primary_observation_type": "flow_station"}


@pytest.mark.parametrize(("model", "values", "match"), [
    (AreaCriteriaConfig, {"mode": "report"}, "report_only"),
    (OutletsConfig, {"candidate_mode": "imported_points"}, "imported_points"),
    (TerritoryConfig, {"mode": "site_catalog_extent"}, "site_catalog_extent"),
    (SpatialSelectionConfig, {"same_mainstem_policy": "keep_best"}, "same_mainstem_policy"),
    (OutputConfig, {"write_candidates": False}, "write_candidates"),
    (OutputConfig, {"write_report_md": False}, "write_report_md"),
    (SiteSelectionInputConfig, {"mode": "auto"}, "auto"),
    (SiteSelectionInputConfig, {"mode": "delineated_catchments"}, "requires catchments_csv"),
    (OutletsConfig, {"snap_strategy": "bdtopage_then_dem", "reference_network_source": "custom"},
     "requires reference_network_path"),
    (SpatialSelectionConfig, {"spatial_quota_mode": "grid"}, "spatial_quota_cell_size_km"),
    (StrategyConfig, AREA_ONLY | {"observation_role": "bonus"}, "observation_role"),
    (StrategyConfig, AREA_ONLY | {"geology_role": "bonus"}, "geology_role"),
    (StrategyConfig, AREA_ONLY | {"primary_axes": ["area", "geology"]}, "primary_axes"),
    (StrategyConfig, {"principle": "observation_led"}, "requires primary_observation_type"),
    (StrategyConfig, GAUGED, "profile='gauged_downstream_station'"),
    (StrategyConfig, GAUGED | {"profile": "gauged_downstream_station", "primary_observation_type": "pz"},
     "primary_observation_type='flow_station'"),
    (StrategyConfig, {"principle": "criteria_crossing", "profile": "gauged_downstream_station"},
     "requires principle='observation_led'"),
    (TerritoryConfig, {"mode": "admin_regions", "country": "FR"}, "at least one region"),
    (TerritoryConfig, {"mode": "admin_regions", "country": "FR", "regions": ["Bretange"]}, "Unknown"),
    (TerritoryConfig, {"mode": "admin_departments"}, "at least one department"),
    (TerritoryConfig, {"mode": "polygon_file"}, "requires polygon_file"),
    (TerritoryConfig, {"mode": "bbox"}, "requires bbox"),
    (DemAreaLightConfig, {"min_area_km2": 125.0, "max_area_km2": 75.0}, "min_area_km2"),
    (DemAreaLightConfig, {"target_area_km2": 50.0}, "target_area_km2"),
    (AreaRangeConfig, {"min_area_km2": 150.0, "max_area_km2": 50.0}, "min_area_km2"),
    (AreaCriteriaConfig, {"mode": "hard_reject", "ranges": [{"min_area_km2": 150.0, "max_area_km2": 50.0}]},
     "min_area_km2"),
    (AreaCriteriaConfig, {"mode": "hard_reject", "hard_min_area_km2": 200.0, "hard_max_area_km2": 100.0},
     "hard_min_area_km2"),
    (AreaCriteriaConfig, {"mode": "hard_reject"}, "at least one area range"),
    (AreaCriteriaConfig, {"mode": "score"}, "requires preferred_area_km2"),
    (AreaCriteriaConfig, {"mode": "score", "preferred_area_km2": 100.0}, "requires score_half_width_fraction"),
])  # fmt: skip
def test_a_table_that_cannot_be_served_is_refused(model, values, match):
    with pytest.raises(ValueError, match=match):
        model.model_validate(values)


@pytest.mark.parametrize(("profile", "tables", "match"), [
    ("gauged", {"outlets": {"candidate_mode": "network_sampling"}}, "station_outlets"),
    ("custom", {"input": {"mode": "dem_area_light"}}, "strategy.profile='area_only'"),
    ("area_only", {"criteria": {"observations": {"flow_station": {"mode": "hard_reject"}}}},
     "flow_station.mode='report_only'"),
    ("area_only", {"criteria": {"observations": {"piezometer_mode": "warning"}}}, "piezometer_mode='report_only'"),
    ("area_only", {"criteria": {"geology": {"mode": "warning"}}}, "geology.mode"),
    ("area_only", {"criteria": {"area": {"mode": "report_only"}}}, "active criterion"),
])  # fmt: skip
def test_a_selection_whose_tables_disagree_is_refused(tmp_path, profile, tables, match):
    with pytest.raises(ValueError, match=match):
        _config(tmp_path, profile, **tables)


@pytest.mark.parametrize(("tables", "key", "advice"), [
    ({"random_seed": 7}, "random_seed", "Remove the key"),
    ({"dem": {"resolution_m": 25.0}}, "resolution_m", "[data.dem]"),
    ({"dem": {"cache_policy": "use_cache_else_download"}}, "cache_policy", "force_refresh"),
    ({"criteria": {"ruleset": "v1"}}, "ruleset", "Remove the key"),
    ({"criteria": {"hard_reject": ["area_range"]}}, "hard_reject", "criteria.area.mode"),
    ({"criteria": {"warning": ["geology"]}}, "warning", "criteria.geology.mode"),
    ({"criteria": {"soft_score": ["record_length"]}}, "soft_score", "own mode"),
    ({"criteria": {"report_only": ["piezometry"]}}, "report_only", "piezometer_mode"),
    ({"criteria": {"geology": {"prefer_diversity": True}}}, "prefer_diversity", "geology.mode = 'stratify'"),
    ({"strategy": {"candidate_mode": "station_outlets"}}, "candidate_mode",
     "site_selection.outlets.candidate_mode"),
    ({"criteria": {"observations": {"flow_station_mode": "hard_reject"}}}, "flow_station_mode",
     "[site_selection.criteria.observations.flow_station]"),
    ({"criteria": {"observations": {"flow_station_max_distance_km": 1.0}}}, "flow_station_max_distance_km",
     "max_station_to_outlet_distance_km"),
])  # fmt: skip
def test_an_unread_key_is_refused_with_what_to_write(tmp_path, tables, key, advice):
    with pytest.raises(ValidationError) as excinfo:
        _config(tmp_path, "custom", **tables)
    assert f"'{key}' is not accepted any more" in str(excinfo.value)
    assert advice in str(excinfo.value)


def test_the_flow_station_table_holds_its_mode_and_distance(tmp_path):
    flow_station = {"mode": "hard_reject", "max_station_to_outlet_distance_km": 2.0}
    cfg = _config(tmp_path, "custom", criteria={"observations": {"flow_station": flow_station}})
    station = cfg.criteria.observations.flow_station
    assert (station.mode, station.max_station_to_outlet_distance_km) == ("hard_reject", 2.0)


def test_the_lake_abacus_id_is_refused_with_lake_id(tmp_path):
    with pytest.raises(ValidationError, match="'id' is not accepted any more.*lake_id"):
        LakeAbacusConfig(sources=[{"path": tmp_path / "abacus.csv"}], id="lac0_abacus")


def _with_engine(tmp_path, engine_id):
    """Revalidate a dump as a TOML read does: ``model_copy`` would run no validator."""
    payload = make_config(tmp_path).model_dump(mode="python")
    return SiteSelectionConfig.model_validate(payload | {"terrain_engine": engine_id})


@pytest.mark.parametrize("engine_id", [registry.builtin_engine_ids()[0], None])
def test_a_project_names_an_installed_engine_or_none_and_never_the_default(tmp_path, engine_id):
    assert _with_engine(tmp_path, engine_id).terrain_engine == engine_id


def test_a_project_naming_an_engine_nobody_installed_is_refused_while_reading(tmp_path):
    with pytest.raises(ValidationError) as raised:
        _with_engine(tmp_path, "no-such-engine")
    assert "site_selection.terrain_engine" in str(raised.value)
    assert registry.ENTRY_POINT_GROUP in str(raised.value)
    assert all(engine_id in str(raised.value) for engine_id in registry.builtin_engine_ids())
