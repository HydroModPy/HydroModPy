from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.reporting.site_selection.plan import render_site_selection_plan_html_report
from hydromodpy.spatial.site_selection.runner import run_site_selection

_STRATEGY = [
    "[site_selection.strategy]",
    'principle = "criteria_crossing"',
    'profile = "area_only"',
    'primary_axes = ["area"]',
    'observation_role = "report_only"',
    'geology_role = "report_only"',
    "",
    "[site_selection.criteria.area]",
    'mode = "hard_reject"',
    "hard_min_area_km2 = 75.0",
    "hard_max_area_km2 = 125.0",
]


def _write_selection(tmp_path: Path, *, input_lines: list[str], extra: list[str]) -> Path:
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                *input_lines,
                "",
                *_STRATEGY,
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                *extra,
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_catchments(tmp_path: Path) -> None:
    (tmp_path / "catchments.csv").write_text(
        "site_id,x,y,area_km2\nsite_ok,0,0,100\nsite_bad,1,1,50\n", encoding="utf-8"
    )


@pytest.mark.fast
def test_plan_mode_writes_the_plan_manifest_and_its_report(tmp_path):
    config_path = _write_selection(
        tmp_path,
        input_lines=['mode = "plan_only"'],
        extra=["[site_selection.output]", "write_report_html = true"],
    )

    run = run_site_selection(
        config_path, plan_report_renderer=render_site_selection_plan_html_report
    )

    assert run.action == "plan"
    assert run.selection_id == "demo"
    assert run.outputs["plan_manifest"] == (tmp_path / "out" / "site_selection_plan.json")
    html = run.outputs["site_selection_report_html"].read_text(encoding="utf-8")
    assert "site selection plan" in html
    assert "No site is selected or rejected" in html


@pytest.mark.fast
def test_delineated_catchments_select_and_write_the_report(tmp_path):
    _write_catchments(tmp_path)
    config_path = _write_selection(
        tmp_path,
        input_lines=[
            'mode = "delineated_catchments"',
            'catchments_csv = "catchments.csv"',
            'region_id = "BZH"',
        ],
        extra=["[site_selection.output]", "write_report_html = true"],
    )

    run = run_site_selection(config_path, report_renderer=render_site_selection_html_report)

    assert run.action == "delineated_catchments"
    assert run.counts == {"selected": 1, "rejected": 1}
    assert (tmp_path / "out" / "selected_sites.csv").is_file()
    assert run.outputs["site_selection_manifest_json"].is_file()
    assert (tmp_path / "out" / "review" / "index.html").is_file()


@pytest.mark.fast
def test_without_a_renderer_no_report_is_written(tmp_path):
    _write_catchments(tmp_path)
    config_path = _write_selection(
        tmp_path,
        input_lines=['mode = "delineated_catchments"', 'catchments_csv = "catchments.csv"'],
        extra=["[site_selection.output]", "write_report_html = true"],
    )

    run = run_site_selection(config_path)

    assert run.outputs["site_selection_manifest_json"].is_file()
    assert "site_selection_report_html" not in run.outputs
    assert not (tmp_path / "out" / "review" / "index.html").exists()


@pytest.mark.fast
def test_a_selection_file_with_a_workflow_mode_is_refused(tmp_path):
    config_path = _write_selection(tmp_path, input_lines=['mode = "plan_only"'], extra=[])
    config_path.write_text(
        '[workflow]\nmode = "site_selection"\n\n' + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="hmp site select"):
        run_site_selection(config_path)


@pytest.mark.fast
def test_the_regional_lab_switch_is_refused_by_name(tmp_path):
    config_path = _write_selection(
        tmp_path,
        input_lines=['mode = "plan_only"'],
        extra=["[site_selection.output]", "write_regional_lab_csv = true"],
    )

    with pytest.raises(ValueError, match="write_regional_lab_csv.*--into-catalog"):
        run_site_selection(config_path)
