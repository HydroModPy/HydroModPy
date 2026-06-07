from __future__ import annotations

import json

import pytest

from hydromodpy.workflow.site_selection import plan_site_selection


@pytest.mark.fast
def test_plan_site_selection_loads_toml_and_resolves_paths(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "area_only_demo"',
                'output_root = "outputs/site_selection/area_only_demo"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Auvergne-Rhone-Alpes"]',
                "",
                "[site_selection.criteria]",
                'ruleset = "france_area_only_v1"',
                'hard_reject = ["dem_coverage", "geometry_validity", "area_range"]',
                'report_only = ["geology", "hydrometry", "piezometry"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "target_area_km2 = 100.0",
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_site_selection(config_path)

    assert plan.config.output_root == tmp_path / "outputs/site_selection/area_only_demo"
    assert plan.manifest["selection_id"] == "area_only_demo"
    assert plan.manifest["strategy"]["profile"] == "area_only"
    assert plan.manifest["strategy"]["effective_profile"] == "area_only"
    assert plan.manifest["criteria"]["area_mode"] == "hard_reject"
    assert "selected" in plan.manifest["planned_outputs"]
    assert "regional_lab_csv" in plan.manifest["planned_outputs"]
    assert "geoparquet" not in plan.manifest["planned_outputs"]
    assert "report_md" not in plan.manifest["planned_outputs"]
    assert "report_html" not in plan.manifest["planned_outputs"]


@pytest.mark.fast
def test_site_selection_plan_can_write_manifest(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "observed_demo"',
                'output_root = "out"',
                "",
                "[site_selection.strategy]",
                'principle = "observation_led"',
                'profile = "gauged_downstream_station"',
                'primary_observation_type = "flow_station"',
                'candidate_mode = "station_outlets"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_site_selection(config_path)
    manifest_path = plan.write_manifest()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["selection_id"] == "observed_demo"
    assert payload["strategy"]["candidate_mode"] == "station_outlets"
    assert payload["strategy"]["effective_profile"] == "gauged_downstream_station"
