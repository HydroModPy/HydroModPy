from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.workflow.site_selection import (
    load_data_dem_config_for_site_selection,
    load_hydrometry_config_for_site_selection,
    load_site_selection_config,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow"


@pytest.mark.fast
def test_bretagne_hydrometry_primary_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_hydrometry_primary.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.strategy.primary_observation_type == "flow_station"
    assert site_cfg.input.mode == "delineated_catchments"
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].product == "QmnJ"


@pytest.mark.fast
def test_bretagne_hydrometry_hubeau_preview_uses_generic_loader():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_hydrometry_50_500_hubeau_preview.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.territory.regions == ["Bretagne"]
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(500.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].product == "QmnJ"
    assert hydrometry_cfg.sources[0].extent == "study_area"


@pytest.mark.fast
def test_auvergne_rhone_alpes_hydrometry_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "auvergne_rhone_alpes_hydrometry_50_150.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.territory.regions == ["Auvergne-Rhone-Alpes"]
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(150.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Auvergne-Rhone-Alpes"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"


@pytest.mark.fast
def test_auvergne_rhone_alpes_hydrometry_preview_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "auvergne_rhone_alpes_hydrometry_preview.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.selection_id == "aura_hydrometry_preview_v1"
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Auvergne-Rhone-Alpes"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].station_ids == [
        "K003002010",
        "K004551001",
        "K010002010",
        "K013401001",
        "K021401001",
    ]


@pytest.mark.fast
def test_bretagne_hydrometry_small_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_hydrometry_50_500_small.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(500.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"
    assert hydrometry_cfg.sources[0].station_ids == [
        "J061161001",
        "J062661001",
        "J110301001",
        "J111401001",
        "J131301001",
        "J132401001",
        "J151301001",
    ]
    assert hydrometry_cfg.sources[0].max_stations == 7


@pytest.mark.fast
def test_bretagne_hydrometry_small_bdtopage_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_hydrometry_50_500_small_bdtopage.toml"

    site_cfg = load_site_selection_config(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.outlets.snap_strategy == "bdtopage_then_dem"
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"
    assert hydrometry_cfg.sources[0].station_ids == [
        "J061161001",
        "J062661001",
        "J110301001",
        "J111401001",
        "J131301001",
        "J132401001",
        "J151301001",
    ]
    assert hydrometry_cfg.sources[0].max_stations == 7


@pytest.mark.fast
def test_normandie_dem_area_light_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "normandie_dem_area_light_100km2.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.regions == ["Normandie"]
    assert site_cfg.hydrology.network_threshold_area_km2 == pytest.approx(1.0)
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.min_area_km2 == pytest.approx(75.0)
    assert site_cfg.dem_area_light.max_area_km2 == pytest.approx(125.0)
    assert site_cfg.dem_area_light.n_basins == 50
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Normandie"]


@pytest.mark.fast
def test_calvados_dem_area_light_fast_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "calvados_dem_area_light_100km2_fast.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["014"]
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.n_basins == 10
    assert site_cfg.dem_area_light.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["014"]


@pytest.mark.fast
def test_manche_dem_area_light_fast_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "manche_dem_area_light_100km2_fast.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["050"]
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.n_basins == 10
    assert site_cfg.dem_area_light.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["050"]
