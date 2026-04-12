from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from launchers.regional_lab.bootstrap import build_site_catalog_from_outlet_table
from launchers.regional_lab.config import RegionalLabConfig
from launchers.regional_lab.launcher import (
    RegionalLabLauncher,
    build_regional_lab_plan,
    build_run_command,
    load_site_catalog,
)


def _load_launchers_main_module():
    module_path = Path(__file__).resolve().parents[3] / "launchers" / "__main__.py"
    spec = importlib.util.spec_from_file_location(
        "launchers_main_regional_lab_test_module",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
                'launcher = "method-comparison"',
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
            "[simulation]\nrun_id = \"demo\"\n",
            encoding="utf-8",
        )
    (configs_dir / "compare_headwater_100km2_outlet_2.toml").write_text(
        "[method_comparison]\ncomparison_id = \"demo\"\n",
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
        Path(config_path).read_text(encoding="utf-8").replace(
            '\n'.join(
                [
                    'format = "csv"',
                    'site_id_field = "outlet_id"',
                    'cluster_id_field = "cluster"',
                    'region_field = "region"',
                    'source_selection_field = "source_selection_id"',
                ]
            ),
            '\n'.join(
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


def test_regional_lab_execution_stops_on_first_failure(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_regional_lab_config(
        tmp_path,
        execute=True,
        continue_on_error=False,
    )
    _write_csv_catalog(tmp_path)
    _write_planned_configs(tmp_path)

    calls: list[list[str]] = []

    def _fake_subprocess_run(command, cwd, check):
        calls.append(list(command))
        returncode = 0 if len(calls) == 1 else 1
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(
        "launchers.regional_lab.launcher.subprocess.run",
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

    def _fake_subprocess_run(command, cwd, check):
        calls.append(list(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "launchers.regional_lab.launcher.subprocess.run",
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

    commands = [
        build_run_command(case, python_executable=Path("python"))
        for case in planned_cases
    ]

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
        "launchers",
        "method-comparison",
        "run",
        str((tmp_path / "configs" / "compare_headwater_100km2_outlet_2.toml").resolve()),
    ]


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


def test_launchers_cli_regional_lab_run_dispatches_to_launcher(monkeypatch) -> None:
    module = _load_launchers_main_module()
    captured: dict[str, Path] = {}
    config_path = Path("sample_regional_lab.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_regional_lab_launcher", _fake_runner)

    code = module.main(["regional-lab", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_regional_lab_bootstrap_dispatches(monkeypatch) -> None:
    module = _load_launchers_main_module()
    captured: dict[str, object] = {}

    def _fake_bootstrap(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(module, "_bootstrap_regional_lab_catalog", _fake_bootstrap)

    code = module.main(
        [
            "regional-lab",
            "bootstrap-catalog",
            "--outlets-table",
            "outlets.csv",
            "--output",
            "site_catalog.csv",
            "--cluster-id",
            "headwater_100km2",
            "--region-id",
            "brittany",
            "--source-selection-id",
            "scan_headwater_100km2",
            "--tag",
            "mesh_ready",
        ]
    )

    assert code == 0
    assert captured["outlets_table"] == Path("outlets.csv").resolve()
    assert captured["output"] == Path("site_catalog.csv").resolve()
    assert captured["cluster_id"] == "headwater_100km2"
    assert captured["region_id"] == "brittany"
    assert captured["source_selection_id"] == "scan_headwater_100km2"
    assert captured["tags"] == ["mesh_ready"]


def test_launchers_cli_regional_lab_template_prints_template(capsys) -> None:
    module = _load_launchers_main_module()

    code = module.main(["regional-lab", "template"])
    captured = capsys.readouterr()

    assert code == 0
    assert "[regional_lab]" in captured.out
    assert "[regional_lab.catalog]" in captured.out
    assert "[[regional_lab.recipe]]" in captured.out


def test_regional_lab_repo_example_expands_existing_cases() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config_path = (
        repo_root
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "regional_lab"
        / "config_headwater_100km2_lab.toml"
    )

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)
    selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)

    assert len(selected_sites) >= 3
    assert [case.case_id for case in planned_cases] == [
        "mf6_reference::headwater_100km2_outlet_2",
        "backend_compare::headwater_100km2_outlet_2",
        "transient_backend_compare::headwater_100km2_outlet_2",
    ]
    assert [case.case_id for case in skipped_cases] == [
        "mf6_reference::headwater_100km2_outlet_27",
        "mf6_reference::headwater_100km2_outlet_34",
        "backend_compare::headwater_100km2_outlet_27",
        "backend_compare::headwater_100km2_outlet_34",
        "transient_backend_compare::headwater_100km2_outlet_27",
        "transient_backend_compare::headwater_100km2_outlet_34",
    ]
