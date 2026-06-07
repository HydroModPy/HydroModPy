from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher
from hydromodpy.analysis.testbed.regional_lab_adapter import regional_plan_to_testbed_cases
from hydromodpy.analysis.testbed.regional_lab_catalog import load_site_catalog
from hydromodpy.analysis.testbed.regional_lab_config import (
    RegionalLabConfig,
    RegionalLabSelectionConfig,
)
from hydromodpy.analysis.testbed.regional_lab_planning import (
    build_regional_lab_plan,
)
from hydromodpy.analysis.testbed.regional_lab_reporting import build_plan_payload
from hydromodpy.analysis.testbed.regional_lab_site_selection import (
    filter_sites,
    site_matches_selection,
)
from hydromodpy.project.dispatch.workflow import run_testbed

from ._regional_lab_builders import (
    write_csv_catalog,
    write_planned_configs,
    write_regional_lab_config,
    write_regional_lab_testbed_profile_config,
)


def test_regional_lab_legacy_launcher_alias_is_removed() -> None:
    import hydromodpy.analysis.testbed.regional_lab as regional_lab

    assert not hasattr(regional_lab, "RegionalLabLauncher")


def test_regional_lab_builds_plan_without_execution(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)
    selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)

    assert [site.site_id for site in selected_sites] == [
        "headwater_100km2_outlet_2",
        "headwater_100km2_outlet_3",
    ]
    assert selected_sites[0].cluster_family == "headwater"
    assert selected_sites[0].cluster_scale == "100km2"
    assert "regional_screening" in selected_sites[0].tags
    assert [case.case_id for case in planned_cases] == [
        "sim_reference::headwater_100km2_outlet_2",
        "sim_reference::headwater_100km2_outlet_3",
        "backend_compare::headwater_100km2_outlet_2",
    ]
    assert [case.case_id for case in skipped_cases] == [
        "backend_compare::headwater_100km2_outlet_3"
    ]

    summary = RegionalLabProfileLauncher(config_path).run()

    assert summary["selected_site_count"] == 2
    assert summary["planned_case_count"] == 3
    assert summary["skipped_case_count"] == 1
    assert summary["executed_case_count"] == 0
    assert Path(summary["plan_path"]).exists()
    assert Path(summary["report_path"]).exists()
    assert Path(summary["site_inventory_csv"]).exists()
    assert Path(summary["recipe_summary_csv"]).exists()
    assert Path(summary["summary_markdown"]).exists()

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["selected_site_count"] == 2
    assert report["planned_case_count"] == 3
    assert report["skipped_case_count"] == 1
    assert report["executed_case_count"] == 0
    assert [case["status"] for case in report["cases"]] == [
        "planned",
        "planned",
        "planned",
    ]
    assert report["skipped_cases"][0]["reason"] == "missing_required_fields"


def test_regional_lab_runs_as_testbed_profile(tmp_path: Path) -> None:
    config_path = write_regional_lab_testbed_profile_config(tmp_path, execute=False)
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    summary = run_testbed(config_path)

    assert summary["lab_id"] == "demo_lab"
    assert summary["selected_site_count"] == 2
    assert summary["planned_case_count"] == 3
    assert summary["skipped_case_count"] == 1
    plan = json.loads(Path(summary["plan_path"]).read_text(encoding="utf-8"))
    assert plan["schema_version"] == "regional_lab_plan_v2"


def test_regional_lab_compatibility_toml_plan_contract_is_stable(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(
        cfg,
        load_site_catalog(cfg.catalog),
    )
    payload = build_plan_payload(
        cfg=cfg,
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
    )

    assert payload["schema_version"] == "regional_lab_plan_v2"
    assert payload["lab_id"] == "demo_lab"
    assert payload["selected_site_count"] == 2
    assert payload["planned_case_count"] == 3
    assert payload["skipped_case_count"] == 1
    assert [site["site_id"] for site in payload["selected_sites"]] == [
        "headwater_100km2_outlet_2",
        "headwater_100km2_outlet_3",
    ]
    assert [
        (case["case_id"], case["launcher"], Path(case["config_path"]).name)
        for case in payload["cases"]
    ] == [
        (
            "sim_reference::headwater_100km2_outlet_2",
            "simulation",
            "run_headwater_100km2_outlet_2.toml",
        ),
        (
            "sim_reference::headwater_100km2_outlet_3",
            "simulation",
            "run_headwater_100km2_outlet_3.toml",
        ),
        (
            "backend_compare::headwater_100km2_outlet_2",
            "comparison",
            "compare_headwater_100km2_outlet_2.toml",
        ),
    ]
    assert [
        (case["case_id"], case["reason"], case["missing_fields"])
        for case in payload["skipped_cases"]
    ] == [
        (
            "backend_compare::headwater_100km2_outlet_3",
            "missing_required_fields",
            ["compare_config"],
        )
    ]
    assert payload["recipes"] == [
        {
            "id": "sim_reference",
            "label": "sim_reference",
            "launcher": "simulation",
            "enabled": True,
            "config_path_template": "{simulation_config}",
            "required_fields": ["simulation_config"],
            "allowed_platforms": [],
        },
        {
            "id": "backend_compare",
            "label": "backend_compare",
            "launcher": "comparison",
            "enabled": True,
            "config_path_template": "{compare_config}",
            "required_fields": ["compare_config"],
            "allowed_platforms": [],
        },
    ]


def test_regional_lab_plan_projects_to_testbed_cases(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    _, planned_cases, _ = build_regional_lab_plan(cfg, load_site_catalog(cfg.catalog))
    testbed_cases = regional_plan_to_testbed_cases(planned_cases)

    assert [case.case_id for case in testbed_cases] == [
        "sim_reference::headwater_100km2_outlet_2",
        "sim_reference::headwater_100km2_outlet_3",
        "backend_compare::headwater_100km2_outlet_2",
    ]
    assert [(case.runner, case.case.variant.axis) for case in testbed_cases] == [
        ("simulation", "sim_reference"),
        ("simulation", "sim_reference"),
        ("comparison", "backend_compare"),
    ]
    assert testbed_cases[0].case.variant.label == ("sim_reference / headwater_100km2_outlet_2")
    assert testbed_cases[0].to_mapping() == {
        "case_id": "sim_reference::headwater_100km2_outlet_2",
        "case_label": "sim_reference / headwater_100km2_outlet_2",
        "axis": "sim_reference",
        "enabled": True,
        "status": "planned",
        "config_path": str((tmp_path / "configs" / "run_headwater_100km2_outlet_2.toml").resolve()),
        "runner": "simulation",
        "regional_case_id": "sim_reference::headwater_100km2_outlet_2",
        "recipe_id": "sim_reference",
        "site_id": "headwater_100km2_outlet_2",
    }


def test_regional_lab_rejects_removed_subprocess_execution_fields(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "validate_config_paths = true\n",
            'execution_backend = "subprocess"\nvalidate_config_paths = true\n',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="execution_backend has been removed"):
        RegionalLabConfig.from_file(config_path)

    config_path = write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "validate_config_paths = true\n",
            "child_timeout_s = 120\nvalidate_config_paths = true\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="child_timeout_s has been removed"):
        RegionalLabConfig.from_file(config_path)


def test_regional_site_selection_filters_by_region_tags_and_enabled(
    tmp_path: Path,
) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    write_csv_catalog(tmp_path)
    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)

    selected = filter_sites(
        sites,
        selection=RegionalLabSelectionConfig(
            regions=("brittany",),
            tags=("mesh_ready",),
            limit=1,
        ),
    )

    assert [site.site_id for site in selected] == ["headwater_100km2_outlet_2"]
    assert site_matches_selection(
        sites[0],
        selection=RegionalLabSelectionConfig(
            regions=("brittany",),
            statuses=("ready",),
            maturity_levels=("validated",),
            tags=("backend_ready",),
        ),
    )
    assert not site_matches_selection(
        sites[2],
        selection=RegionalLabSelectionConfig(
            regions=("brittany",),
            tags=("mesh_ready",),
        ),
    )
    assert site_matches_selection(
        sites[2],
        selection=RegionalLabSelectionConfig(
            regions=("brittany",),
            tags=("mesh_ready",),
            include_disabled=True,
        ),
    )


def test_regional_lab_recipe_can_skip_unsupported_platform(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    unsupported_platform = "linux" if sys.platform.startswith("win") else "windows"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'id = "backend_compare"\nlauncher = "comparison"\n',
            'id = "backend_compare"\n'
            'launcher = "comparison"\n'
            f'allowed_platforms = ["{unsupported_platform}"]\n',
        ),
        encoding="utf-8",
    )
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    _, planned_cases, skipped_cases = build_regional_lab_plan(cfg, load_site_catalog(cfg.catalog))

    assert [case.case_id for case in planned_cases] == [
        "sim_reference::headwater_100km2_outlet_2",
        "sim_reference::headwater_100km2_outlet_3",
    ]
    assert [case.case_id for case in skipped_cases] == [
        "backend_compare::headwater_100km2_outlet_2",
        "backend_compare::headwater_100km2_outlet_3",
    ]
    assert all(case.reason == "unsupported_platform" for case in skipped_cases)
    assert unsupported_platform in skipped_cases[0].detail
