from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from hydromodpy.reporting.site_selection.intent import (
    site_selection_report_html_requested,
)
from hydromodpy.workflow.site_selection import (
    load_data_dem_config_for_site_selection,
    load_hydrometry_config_for_site_selection,
    load_site_selection_config,
    run_site_selection_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow"


@pytest.mark.fast
def test_site_selection_examples_use_generic_report_html_contract():
    config_paths = sorted((EXAMPLE_ROOT / "configs").glob("*.toml"))

    assert config_paths
    for config_path in config_paths:
        text = config_path.read_text(encoding="utf-8-sig")
        assert "write_report_html" not in text, config_path.name
        assert "[report.html]" in text, config_path.name
        assert 'profile = "site_selection"' in text, config_path.name
        assert "build_at_end = true" in text, config_path.name


@pytest.mark.fast
def test_site_selection_examples_do_not_duplicate_dem_admin_selectors():
    config_paths = sorted((EXAMPLE_ROOT / "configs").glob("*.toml"))

    assert config_paths
    for config_path in config_paths:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        dem_sources = raw.get("data", {}).get("dem", {}).get("sources", [])
        for source in dem_sources:
            assert "regions" not in source, config_path.name
            assert "departments" not in source, config_path.name


@pytest.mark.fast
def test_site_selection_examples_keep_dem_resolution_in_data_sources():
    config_paths = sorted((EXAMPLE_ROOT / "configs").glob("*.toml"))

    assert config_paths
    for config_path in config_paths:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        dem_sources = raw.get("data", {}).get("dem", {}).get("sources", [])
        if not dem_sources:
            continue
        site_dem = raw.get("site_selection", {}).get("dem", {})
        assert "resolution_m" not in site_dem, config_path.name
        assert any("resolution_m" in source for source in dem_sources), config_path.name


@pytest.mark.fast
def test_bretagne_jauge_csv_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_jauge_csv_10_1000km2.toml"

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
def test_bretagne_jauge_regional_uses_generic_loader():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_jauge_50_500km2.toml"

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
def test_aura_jauge_regional_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "aura_jauge_regional_50_150km2.toml"

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
def test_aura_jauge_5stations_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "aura_jauge_5stations.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.selection_id == "aura_jauge_5stations_v1"
    assert "area_range" not in site_cfg.criteria.warning
    assert site_cfg.criteria.area.ranges == []
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
def test_bretagne_jauge_7stations_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "bretagne_jauge_7stations.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.selection_id == "bretagne_jauge_7stations"
    assert site_cfg.outlets.snap_strategy == "bdtopage_then_dem"
    assert site_cfg.outlets.dem_snap_max_distance_m == 150
    assert site_cfg.outlets.reference_network_snap_max_distance_m == pytest.approx(100.0)
    assert site_cfg.spatial_selection.allow_nested_basins is True
    assert site_cfg.spatial_selection.max_pairwise_basin_overlap_fraction is None
    assert site_cfg.criteria.hard_reject == ["delineation_failure"]
    assert site_cfg.criteria.warning == []
    assert site_cfg.criteria.ranking_preference == []
    assert site_cfg.criteria.report_only == []
    assert site_cfg.criteria.area.ranges == []
    assert site_selection_report_html_requested(site_cfg) is True
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert dem_cfg.sources[0].resolution_m == pytest.approx(25.0)
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent is None
    assert hydrometry_cfg.sources[0].station_ids == [
        "J061161001",
        "J062661001",
        "J110301001",
        "J111401001",
        "J131301001",
        "J132401001",
        "J151301001",
    ]
    assert hydrometry_cfg.sources[0].max_stations is None


@pytest.mark.fast
def test_finistere_jauge_elorn_dem_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "finistere_jauge_elorn_dem.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["029"]
    assert site_cfg.outlets.snap_strategy == "dem_accumulation"
    assert "area_range" not in site_cfg.criteria.warning
    assert site_cfg.criteria.area.ranges == []
    assert site_selection_report_html_requested(site_cfg) is True
    assert dem_cfg is not None
    assert dem_cfg.sources[0].departments == ["029"]
    assert hydrometry_cfg.sources[0].station_ids == ["J341303001"]
    assert hydrometry_cfg.sources[0].max_stations == 1


@pytest.mark.fast
def test_normandie_non_jauge_dem_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "normandie_non_jauge_dem_50bassins_100km2.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_target"
    assert site_cfg.territory.regions == ["Normandie"]
    assert site_cfg.hydrology.network_threshold_area_km2 == pytest.approx(1.0)
    assert site_cfg.dem_area_target is not None
    assert site_cfg.dem_area_target.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_target.min_area_km2 == pytest.approx(75.0)
    assert site_cfg.dem_area_target.max_area_km2 == pytest.approx(125.0)
    assert site_cfg.dem_area_target.n_basins == 50
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Normandie"]


@pytest.mark.fast
def test_calvados_non_jauge_dem_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "calvados_non_jauge_dem_10bassins_100km2.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_target"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["014"]
    assert site_cfg.dem_area_target is not None
    assert site_cfg.dem_area_target.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_target.n_basins == 10
    assert site_cfg.dem_area_target.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["014"]


@pytest.mark.fast
def test_manche_non_jauge_dem_example_loads():
    config_path = EXAMPLE_ROOT / "configs" / "manche_non_jauge_dem_10bassins_100km2.toml"

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path)

    assert site_cfg.input.mode == "dem_area_target"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["050"]
    assert site_cfg.dem_area_target is not None
    assert site_cfg.dem_area_target.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_target.n_basins == 10
    assert site_cfg.dem_area_target.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["050"]


@pytest.mark.fast
def test_bretagne_jauge_csv_example_runs_from_fixture(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path / "workspace"))
    work_example = tmp_path / "17_site_selection_workflow"
    shutil.copytree(
        EXAMPLE_ROOT,
        work_example,
        ignore=shutil.ignore_patterns("data", "outputs"),
    )
    config_path = work_example / "configs" / "bretagne_jauge_csv_10_1000km2.toml"
    fixture_dem = work_example / "fixtures" / "dem" / "bretagne_synthetic_dem.tif"

    def fake_fetch_ign_dem(*, output_dir, bbox, departments=None, **kwargs):
        assert departments == ["022", "029", "035", "056"]
        assert kwargs["dataset"] == "bd-alti"
        assert kwargs["resolution_m"] == 25.0
        return fixture_dem

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 2
    assert summary["rejected"] == 2
    assert summary["site_selection_report_html"]
    assert (
        work_example
        / "outputs"
        / "bretagne_jauge_csv_10_1000km2_v1"
        / "site_selection_manifest.json"
    ).is_file()
    assert (
        work_example
        / "outputs"
        / "bretagne_jauge_csv_10_1000km2_v1"
        / "review"
        / "index.html"
    ).is_file()
    assert (
        work_example
        / "outputs"
        / "bretagne_jauge_csv_10_1000km2_v1"
        / "review"
        / "site_selection_map.png"
    ).is_file()
    assert (
        work_example
        / "outputs"
        / "bretagne_jauge_csv_10_1000km2_v1"
        / "report_artifact_manifest.json"
    ).is_file()
    assert (
        work_example
        / "outputs"
        / "bretagne_jauge_csv_10_1000km2_v1"
        / "observation_points.geojson"
    ).is_file()
    observations = json.loads(
        (
            work_example
            / "outputs"
            / "bretagne_jauge_csv_10_1000km2_v1"
            / "observation_points.geojson"
        ).read_text(encoding="utf-8")
    )
    assert {feature["properties"]["observation_type"] for feature in observations["features"]} == {
        "flow_station",
        "piezometer",
    }


@pytest.mark.fast
def test_aura_non_jauge_csv_bassins_example_runs_from_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(tmp_path / "workspace"))
    work_example = tmp_path / "17_site_selection_workflow"
    shutil.copytree(
        EXAMPLE_ROOT,
        work_example,
        ignore=shutil.ignore_patterns("data", "outputs"),
    )
    config_path = work_example / "configs" / "aura_non_jauge_csv_50_150km2.toml"
    fixture_dem = work_example / "fixtures" / "dem" / "bretagne_synthetic_dem.tif"

    def fake_fetch_ign_dem(*, output_dir, bbox, departments=None, **kwargs):
        assert departments == [
            "001",
            "003",
            "007",
            "015",
            "026",
            "038",
            "042",
            "043",
            "063",
            "069",
            "073",
            "074",
        ]
        assert kwargs["dataset"] == "bd-alti"
        assert kwargs["resolution_m"] == 25.0
        return fixture_dem

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 20
    assert summary["rejected"] == 0
    assert summary["selected_outlets_geojson"]
    assert summary["selected_basins_geojson"]
    assert summary["site_selection_map_png"]
    aura_output = work_example / "outputs" / "aura_non_jauge_csv_50_150km2_v1"
    assert (aura_output / "selected_sites.csv").is_file()
    assert (aura_output / "regional_lab_sites.csv").is_file()
    assert (aura_output / "selected_outlets.geojson").is_file()
    assert (aura_output / "rejected_outlets.geojson").is_file()
    assert (aura_output / "selected_basins.geojson").is_file()
    assert (aura_output / "site_selection_manifest.json").is_file()
    assert (aura_output / "review" / "index.html").is_file()
    assert (aura_output / "review" / "site_selection_map.png").is_file()
    assert (aura_output / "report_artifact_manifest.json").is_file()
    selected_basins = json.loads(
        (
            aura_output / "selected_basins.geojson"
        ).read_text(encoding="utf-8")
    )
    assert len(selected_basins["features"]) == 20
    assert selected_basins["hydromodpy_skipped_basins"] == []
