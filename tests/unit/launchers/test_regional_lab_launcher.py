from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.analysis.batch.batch_catalog import load_site_catalog
from hydromodpy.analysis.batch.batch_execution import (
    _extract_comparison_child_artifacts,
    _extract_method_comparison_child_artifacts,
)
from hydromodpy.analysis.batch.batch_planning import (
    build_regional_lab_plan,
    build_run_command,
)
from hydromodpy.analysis.batch.bootstrap import build_site_catalog_from_outlet_table
from hydromodpy.analysis.batch.config import RegionalLabConfig
from hydromodpy.analysis.batch.runtime import RegionalLabLauncher


def _write_regional_lab_config(
    tmp_path: Path,
    *,
    execute: bool = False,
    continue_on_error: bool = True,
    catalog_name: str = "site_catalog.csv",
) -> Path:
    config_path = tmp_path / "regional_lab.toml"
    config_path.write_text(
        "\n".join(
            [
                "[regional_lab]",
                'lab_id = "demo_lab"',
                'output_root = "outputs"',
                f"execute = {'true' if execute else 'false'}",
                f"continue_on_error = {'true' if continue_on_error else 'false'}",
                "validate_config_paths = true",
                "resume_from_report = true",
                "skip_completed_cases = true",
                "",
                "[regional_lab.catalog]",
                f'path = "{catalog_name}"',
                'format = "csv"',
                'site_id_field = "outlet_id"',
                'cluster_id_field = "cluster"',
                'region_field = "region"',
                'source_selection_field = "source_selection_id"',
                'status_field = "site_status"',
                'maturity_field = "maturity"',
                'tags_field = "tags"',
                'enabled_field = "enabled"',
                'path_fields = ["simulation_config", "compare_config"]',
                'tag_separator = ";"',
                "",
                "[regional_lab.selection]",
                'cluster_ids = ["headwater_100km2"]',
                'tags = ["mesh_ready"]',
                "",
                "[[regional_lab.cluster_rule]]",
                'id = "headwater_enrichment"',
                'field_equals = { source_selection_id = "scan_headwater_100km2" }',
                'set_cluster_family = "headwater"',
                'set_cluster_scale = "100km2"',
                'cluster_tags = ["regional_screening"]',
                "",
                "[[regional_lab.recipe]]",
                'id = "sim_reference"',
                'launcher = "simulation"',
                'families = ["headwater"]',
                'required_fields = ["simulation_config"]',
                'config_path_template = "{simulation_config}"',
                "",
                "[[regional_lab.recipe]]",
                'id = "backend_compare"',
                'launcher = "comparison"',
                'families = ["headwater"]',
                'required_fields = ["compare_config"]',
                'config_path_template = "{compare_config}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _write_csv_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / "site_catalog.csv"
    catalog_path.write_text(
        "\n".join(
            [
                "outlet_id,cluster,region,source_selection_id,site_status,maturity,tags,enabled,simulation_config,compare_config",
                "headwater_100km2_outlet_2,headwater_100km2,brittany,scan_headwater_100km2,ready,validated,mesh_ready;backend_ready,true,configs/run_headwater_100km2_outlet_2.toml,configs/compare_headwater_100km2_outlet_2.toml",
                "headwater_100km2_outlet_3,headwater_100km2,brittany,scan_headwater_100km2,prototype,screening,mesh_ready,true,configs/run_headwater_100km2_outlet_3.toml,",
                "s3_10km2_outlet_1,s3_10km2,brittany,scan_s3_10km2,inventory,screening,mesh_ready,false,,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return catalog_path


def _write_jsonl_catalog(tmp_path: Path) -> Path:
    catalog_path = tmp_path / "site_catalog.jsonl"
    rows = [
        {
            "site_id": "site_a",
            "cluster_id": "cluster_a",
            "region_id": "region_a",
            "site_status": "ready",
            "maturity": "validated",
            "tags": ["mesh_ready", "backend_ready"],
            "enabled": True,
        },
        {
            "site_id": "site_b",
            "cluster_id": "cluster_b",
            "region_id": "region_a",
            "site_status": "inventory",
            "maturity": "screening",
            "tags": ["mesh_ready"],
            "enabled": False,
        },
    ]
    catalog_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return catalog_path


def _write_planned_configs(tmp_path: Path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    for site_id in ("headwater_100km2_outlet_2", "headwater_100km2_outlet_3"):
        (configs_dir / f"run_{site_id}.toml").write_text(
            '[simulation]\nrun_id = "demo"\n',
            encoding="utf-8",
        )
    (configs_dir / "compare_headwater_100km2_outlet_2.toml").write_text(
        "\n".join(
            [
                'workflow = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo"',
                "",
                "[[comparison.simulation]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
                "",
                "[[comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_regional_lab_builds_plan_without_execution(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=False)
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)

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

    summary = RegionalLabLauncher(config_path).run()

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


def test_regional_lab_supports_jsonl_catalog(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(
        tmp_path,
        execute=False,
        catalog_name="site_catalog.jsonl",
    )
    (tmp_path / "regional_lab.toml").write_text(
        Path(config_path)
        .read_text(encoding="utf-8")
        .replace(
            "\n".join(
                [
                    'format = "csv"',
                    'site_id_field = "outlet_id"',
                    'cluster_id_field = "cluster"',
                    'region_field = "region"',
                    'source_selection_field = "source_selection_id"',
                ]
            ),
            "\n".join(
                [
                    'format = "jsonl"',
                    'site_id_field = "site_id"',
                    'cluster_id_field = "cluster_id"',
                    'region_field = "region_id"',
                    'source_selection_field = "source_selection_id"',
                ]
            ),
        ),
        encoding="utf-8",
    )
    _write_jsonl_catalog(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)

    assert [site.site_id for site in sites] == ["site_a", "site_b"]
    assert sites[0].tags == ("mesh_ready", "backend_ready")
    assert sites[1].enabled is False


def test_regional_lab_supports_utf8_bom_csv_catalog(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=False)
    catalog_path = tmp_path / "site_catalog.csv"
    catalog_path.write_text(
        "\n".join(
            [
                '"outlet_id","cluster","region","source_selection_id","site_status","maturity","tags","enabled","simulation_config","compare_config"',
                '"headwater_100km2_outlet_2","headwater_100km2","brittany","scan_headwater_100km2","ready","validated","mesh_ready","true","configs/run_headwater_100km2_outlet_2.toml","configs/compare_headwater_100km2_outlet_2.toml"',
            ]
        )
        + "\n",
        encoding="utf-8-sig",
    )
    _write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)

    assert [site.site_id for site in sites] == ["headwater_100km2_outlet_2"]


def test_regional_lab_recipe_can_skip_unsupported_platform(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=False)
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
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)

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


def test_regional_lab_execution_stops_on_first_failure(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(
        tmp_path,
        execute=True,
        continue_on_error=False,
    )
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)

    calls: list[list[str]] = []

    def _fake_subprocess_run(command, cwd, check, timeout=None):
        calls.append(list(command))
        returncode = 0 if len(calls) == 1 else 1
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(
        "hydromodpy.analysis.batch.runtime.subprocess.run",
        _fake_subprocess_run,
    )

    summary = RegionalLabLauncher(config_path).run()

    assert summary["planned_case_count"] == 3
    assert summary["skipped_case_count"] == 1
    assert summary["executed_case_count"] == 2
    assert summary["failed_case_count"] == 1
    assert calls[0] == [
        str(Path(sys.executable)),
        "-m",
        "launchers",
        "simulation",
        str((tmp_path / "configs" / "run_headwater_100km2_outlet_2.toml").resolve()),
    ]
    assert calls[1] == [
        str(Path(sys.executable)),
        "-m",
        "launchers",
        "simulation",
        str((tmp_path / "configs" / "run_headwater_100km2_outlet_3.toml").resolve()),
    ]

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["executed_case_count"] == 2
    assert report["failed_case_count"] == 1
    assert report["cases"][0]["status"] == "ok"
    assert report["cases"][1]["status"] == "failed"
    assert report["cases"][2]["status"] == "planned"
    assert report["skipped_cases"][0]["case_id"] == "backend_compare::headwater_100km2_outlet_3"


def test_regional_lab_resume_skips_completed_cases(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=True)
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)

    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "regional_lab_report.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "sim_reference::headwater_100km2_outlet_2",
                        "status": "ok",
                    }
                ]
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def _fake_subprocess_run(command, cwd, check, timeout=None):
        calls.append(list(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "hydromodpy.analysis.batch.runtime.subprocess.run",
        _fake_subprocess_run,
    )

    summary = RegionalLabLauncher(config_path).run()

    assert summary["executed_case_count"] == 2
    assert summary["reused_case_count"] == 1
    assert len(calls) == 2
    assert calls[0][-1].endswith("run_headwater_100km2_outlet_3.toml")
    assert calls[1][-1].endswith("compare_headwater_100km2_outlet_2.toml")

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["reused_case_count"] == 1
    assert report["cases"][0]["status"] == "skipped_existing_ok"


def test_regional_lab_build_run_command_dispatches_launchers(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=False)
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)
    cfg = RegionalLabConfig.from_file(config_path)
    _, planned_cases, _ = build_regional_lab_plan(cfg, load_site_catalog(cfg.catalog))

    commands = [build_run_command(case, python_executable=Path("python")) for case in planned_cases]

    assert commands[0] == [
        "python",
        "-m",
        "launchers",
        "simulation",
        str((tmp_path / "configs" / "run_headwater_100km2_outlet_2.toml").resolve()),
    ]
    assert commands[2] == [
        "python",
        "-m",
        "hydromodpy",
        "run",
        str((tmp_path / "configs" / "compare_headwater_100km2_outlet_2.toml").resolve()),
    ]


def test_regional_lab_keeps_legacy_method_comparison_command(tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'launcher = "comparison"',
            'launcher = "method-comparison"',
        ),
        encoding="utf-8",
    )
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)
    cfg = RegionalLabConfig.from_file(config_path)
    _, planned_cases, _ = build_regional_lab_plan(cfg, load_site_catalog(cfg.catalog))

    command = build_run_command(planned_cases[2], python_executable=Path("python"))

    assert command == [
        "python",
        "-m",
        "launchers",
        "method-comparison",
        "run",
        str((tmp_path / "configs" / "compare_headwater_100km2_outlet_2.toml").resolve()),
    ]


def test_regional_lab_extracts_method_comparison_child_artifacts(tmp_path: Path) -> None:
    config_path = tmp_path / "compare_case.toml"
    comparison_root = tmp_path / "comparison_outputs"
    comparison_root.mkdir(parents=True, exist_ok=True)
    (comparison_root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "comparison_id": "demo_compare",
                "reference_variant": "reference",
                "wall_time_seconds": 12.5,
                "n_metric_rows": 3,
                "n_difference_rows": 2,
                "n_observable_rows": 1,
                "variants": [
                    {"id": "reference", "status": "completed"},
                    {"id": "candidate", "status": "failed"},
                ],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (comparison_root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "summary": [
                    {"observable": "head", "rmse": 1.5, "mae": 0.8},
                    {"observable": "flow", "rmse": 2.0, "mae": 1.1},
                ],
                "differences": [{"observable": "head"}, {"observable": "flow"}],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                f'output_root = "{comparison_root.as_posix()}"',
                "",
                "[[method_comparison.variant]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
                "",
                "[[method_comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = _extract_method_comparison_child_artifacts(config_path)

    assert artifacts["child_artifact_status"] == "resolved"
    assert artifacts["child_comparison_id"] == "demo_compare"
    assert artifacts["child_reference_variant"] == "reference"
    assert artifacts["child_wall_time_seconds"] == 12.5
    assert artifacts["child_variant_count"] == 2
    assert artifacts["child_completed_variant_count"] == 1
    assert artifacts["child_failed_variant_count"] == 1
    assert artifacts["child_summary_max_rmse"] == 2.0
    assert artifacts["child_summary_max_mae"] == 1.1


def test_regional_lab_extracts_canonical_comparison_child_artifacts(tmp_path: Path) -> None:
    config_path = tmp_path / "compare_case.toml"
    comparison_root = tmp_path / "comparison_outputs"
    comparison_root.mkdir(parents=True, exist_ok=True)
    (comparison_root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "comparison_id": "demo_compare",
                "reference_variant": "reference",
                "wall_time_seconds": 12.5,
                "n_metric_rows": 3,
                "n_difference_rows": 2,
                "n_observable_rows": 1,
                "variants": [
                    {"id": "reference", "status": "completed"},
                    {"id": "candidate", "status": "failed"},
                ],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (comparison_root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "summary": [{"observable": "head", "rmse": 1.5, "mae": 0.8}],
                "differences": [{"observable": "head"}],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo_compare"',
                f'output_root = "{comparison_root.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
                "",
                "[[comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = _extract_comparison_child_artifacts(config_path)

    assert artifacts["child_artifact_kind"] == "comparison"
    assert artifacts["child_artifact_status"] == "resolved"
    assert artifacts["child_comparison_id"] == "demo_compare"
    assert artifacts["child_reference_variant"] == "reference"
    assert artifacts["child_summary_max_rmse"] == 1.5


def test_regional_lab_bootstrap_catalog_merges_manifest(tmp_path: Path) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "2,100.0,200.0,98.5",
                "3,110.0,210.0,101.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "mesh_manifest.csv"
    manifest_path.write_text(
        "\n".join(
            [
                "outlet_id,catch_name,status,x_outlet,y_outlet,output_mesh,output_summary_json,output_figure,output_figure_regional,error",
                "2,headwater_2,ok,100.0,200.0,C:/tmp/mesh_2.msh,C:/tmp/summary_2.json,,,",
                "3,headwater_3,failed,110.0,210.0,,,,boom",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "site_catalog_bootstrapped.csv"

    summary = build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="headwater_100km2",
        cluster_label="Headwater 100 km2",
        cluster_family="headwater",
        cluster_scale="100km2",
        region_id="brittany",
        source_selection_id="scan_headwater_100km2",
        manifest_csv=manifest_path,
        default_tags=("regional_screening",),
    )

    assert summary["site_count"] == 2
    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("site_id,site_label,cluster_id")
    assert "headwater_100km2_outlet_2" in rows[1]
    assert "mesh_ready" in rows[1]
    assert "C:/tmp" in rows[1]


def test_regional_lab_bootstrap_catalog_scans_mesh_run_root(tmp_path: Path) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "3,100.0,200.0,10.2",
                "4,110.0,210.0,10.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_run_root = tmp_path / "mesh_runs"
    bundle_dir = mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3.msh").write_text(
        "", encoding="utf-8"
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_summary.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3.png").write_text(
        "", encoding="utf-8"
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_regional.png").write_text(
        "",
        encoding="utf-8",
    )

    output_path = tmp_path / "site_catalog_bootstrapped.csv"
    summary = build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="s3_10km2",
        cluster_label="S3 10 km2",
        cluster_family="s3",
        cluster_scale="10km2",
        region_id="brittany",
        source_selection_id="scan_s3_10km2",
        mesh_run_root=mesh_run_root,
    )

    assert summary["mesh_run_root_scanned"] is True
    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert "mesh_ready" in rows[1]
    assert "discovered" in rows[1]
    assert "mesh_catchment_outlet_3_bundle" in rows[1]


def test_regional_lab_bootstrap_catalog_inspects_bundle_readiness(tmp_path: Path) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "3,100.0,200.0,10.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_run_root = tmp_path / "mesh_runs"
    mesh_dir = mesh_run_root / "mesh_outlet_3"
    bundle_dir = mesh_dir / "mesh_catchment_outlet_3_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (mesh_dir / "mesh_catchment_outlet_3.msh").write_text("", encoding="utf-8")
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
                "0,triangle,0,1,2,,1.0,2.0,3.0,100.0,100.0,50.0,50.0,1,1,1.0e-6,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "hydraulic_properties": {
                    "storage_coefficient": {
                        "default_value": None,
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "site_catalog_bootstrapped.csv"
    build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="s3_10km2",
        cluster_label="S3 10 km2",
        cluster_family="s3",
        cluster_scale="10km2",
        region_id="brittany",
        source_selection_id="scan_s3_10km2",
        mesh_run_root=mesh_run_root,
    )

    with output_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["mesh_bundle_dir"].endswith("mesh_catchment_outlet_3_bundle")
    assert rows[0]["bundle_cell_count"] == "1"
    assert rows[0]["bundle_missing_top_centroid_count"] == "0"
    assert rows[0]["bundle_missing_storage_coefficient_count"] == "1"
    assert rows[0]["bundle_boussinesq_steady_ready"] == "true"
    assert rows[0]["bundle_boussinesq_transient_ready"] == "false"
    assert "boussinesq_steady_ready" in rows[0]["tags"]


def test_regional_lab_bootstrap_catalog_infers_bundle_dir_from_manifest_mesh_path(
    tmp_path: Path,
) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "27,100.0,200.0,98.5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_dir = tmp_path / "mesh_gallery_outlet_27"
    bundle_dir = mesh_dir / "mesh_catchment_outlet_27_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = mesh_dir / "mesh_catchment_outlet_27.msh"
    mesh_path.write_text("", encoding="utf-8")
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
                "0,triangle,0,1,2,,1.0,2.0,3.0,100.0,100.0,50.0,50.0,1,1,1.0e-6,0.15",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text("{}\n", encoding="utf-8")
    manifest_path = tmp_path / "mesh_manifest.csv"
    manifest_path.write_text(
        "\n".join(
            [
                "outlet_id,catch_name,status,x_outlet,y_outlet,output_mesh,output_summary_json,output_figure,output_figure_regional,error",
                f"27,headwater_27,ok,100.0,200.0,{mesh_path.as_posix()},,,,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "site_catalog_bootstrapped.csv"

    build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="headwater_100km2",
        cluster_label="Headwater 100 km2",
        cluster_family="headwater",
        cluster_scale="100km2",
        region_id="brittany",
        source_selection_id="scan_headwater_100km2",
        manifest_csv=manifest_path,
    )

    with output_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["mesh_bundle_dir"] == str(bundle_dir.resolve())
    assert rows[0]["bundle_boussinesq_steady_ready"] == "true"
    assert rows[0]["bundle_boussinesq_transient_ready"] == "true"
    assert "boussinesq_transient_ready" in rows[0]["tags"]
