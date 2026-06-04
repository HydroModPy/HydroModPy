from __future__ import annotations

import pytest

from hydromodpy.workflow.site_selection import run_site_selection_workflow


@pytest.mark.fast
def test_run_site_selection_workflow_plan_mode_writes_manifest(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "plan_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "plan_only"',
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
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "plan"
    assert summary["selection_id"] == "plan_demo"
    assert (tmp_path / "out" / "site_selection_plan.json").is_file()
    assert summary["site_selection_report_html"]
    assert (tmp_path / "out" / "review" / "index.html").is_file()
    html = (tmp_path / "out" / "review" / "index.html").read_text(encoding="utf-8")
    assert "Rapport HTML de plan" in html
    assert "Aucun site n'est retenu ou rejete" in html


@pytest.mark.fast
def test_run_site_selection_workflow_uses_predelineated_catchments(tmp_path):
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x,y,area_km2",
                "site_ok,0,0,100",
                "site_bad,1,1,50",
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "select_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "delineated_catchments"',
                'catchments_csv = "catchments.csv"',
                'region_id = "AURA"',
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
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 1
    assert summary["rejected"] == 1
    assert (tmp_path / "out" / "selected_sites.csv").is_file()
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()
    assert (tmp_path / "out" / "review" / "index.html").is_file()


@pytest.mark.fast
def test_run_site_selection_workflow_writes_manifest_without_html_by_default(tmp_path):
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_ok,0,0,100\n", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "manifest_only_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "delineated_catchments"',
                'catchments_csv = "catchments.csv"',
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
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["selected"] == 1
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()
    assert not (tmp_path / "out" / "review" / "index.html").exists()
    assert summary["site_selection_report_html"] == ""
