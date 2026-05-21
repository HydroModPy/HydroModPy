from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.analysis.testbed.config import TestbedConfig as MethodTestbedConfig
from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
from hydromodpy.analysis.testbed.runtime import TestbedLauncher as MethodTestbedLauncher
from hydromodpy.core.toml_io import load_toml_with_base_config


def _write_mesh_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "mesh"',
                "",
                "[workspace]",
                'project_root = "mesh_outputs/base"',
                "",
                "[simulation]",
                'name = "mesh_base"',
                "",
                "[[simulation.process]]",
                'id = "mesh_main"',
                'type = "mesh"',
                'backend = "catchment"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "rivers_only"',
                "",
                "[mesh_catchment.zone_meshing]",
                "global_size = 200.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_flow_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                'project_root = "flow_outputs/base"',
                "",
                "[simulation]",
                'name = "flow_base"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
                "",
                "[flow]",
                'flow_regime = "steady"',
                'param_list = ["K"]',
                "",
                "[flow.param.K.field]",
                'kind = "homogeneous"',
                'unit = "m/s"',
                'value = "1e-5 m/s"',
                "",
                "[display]",
                "enabled = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_comparison_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "comparison_base"',
                'output_root = "comparison_outputs/base"',
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


def test_testbed_config_parses_mesh_variants(tmp_path: Path) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    config_path = tmp_path / "testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "mesh_resolution"',
                'subject = "mesh"',
                'purpose = "robustness"',
                'base_config = "mesh_base.toml"',
                'output_root = "outputs/testbed"',
                "execute = false",
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.variant.overlay.mesh_catchment.zone_meshing]",
                "global_size = 400.0",
                "",
                "[[testbed.metric]]",
                'name = "n_cells"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = MethodTestbedConfig.from_file(config_path)

    assert cfg.id == "mesh_resolution"
    assert cfg.subject == "mesh"
    assert cfg.runner.type == "simulation"
    assert cfg.base_config_path == base_config.resolve()
    assert cfg.output_root == (tmp_path / "outputs/testbed").resolve()
    assert cfg.execute is False
    assert cfg.variants[0].overlay["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    assert cfg.metrics[0].source == "n_cells"


def test_testbed_config_rejects_removed_mesh_catchment_runner(tmp_path: Path) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    config_path = tmp_path / "testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "mesh_resolution"',
                'subject = "mesh"',
                'base_config = "mesh_base.toml"',
                "",
                "[testbed.runner]",
                'type = "mesh_catchment"',
                "",
                "[[testbed.variant]]",
                'id = "coarse"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported testbed.runner.type 'mesh_catchment'"):
        MethodTestbedConfig.from_file(config_path)


def test_generic_testbed_config_rejects_profile_launcher_config(tmp_path: Path) -> None:
    config_path = tmp_path / "regional_profile.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'profile = "regional_lab"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="profile='regional_lab'.*profile dispatcher"):
        MethodTestbedConfig.from_file(config_path)


def test_testbed_config_parses_flow_variants(tmp_path: Path) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_k_sensitivity"',
                'subject = "flow"',
                'purpose = "robustness"',
                'base_config = "flow_base.toml"',
                "execute = false",
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.variant.overlay.flow.param.K.field]",
                'value = "5e-6 m/s"',
                "",
                "[[testbed.metric]]",
                'name = "sim_id"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = MethodTestbedConfig.from_file(config_path)

    assert cfg.id == "flow_k_sensitivity"
    assert cfg.subject == "flow"
    assert cfg.runner.type == "simulation"
    assert cfg.runner.no_display is True
    assert cfg.base_config_path == base_config.resolve()
    assert cfg.variants[0].overlay["flow"]["param"]["K"]["field"]["value"] == "5e-6 m/s"


def test_flow_testbed_requires_separate_base_config(tmp_path: Path) -> None:
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'subject = "flow"',
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "baseline"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires testbed.base_config"):
        MethodTestbedConfig.from_file(config_path)


def test_testbed_launcher_materializes_child_configs_without_executing(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    config_path = tmp_path / "testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "mesh_resolution"',
                'base_config = "mesh_base.toml"',
                "execute = false",
                "",
                "[[testbed.variant]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.variant.overlay.mesh_catchment.zone_meshing]",
                "global_size = 400.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    generated = Path(summary["generated_configs_dir"]) / "coarse.toml"
    assert generated.exists()
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "simulation"
    assert child_payload["simulation"]["process"][0]["type"] == "mesh"
    assert "testbed" not in child_payload
    assert child_payload["mesh_catchment"]["constraints_mode"] == "rivers_only"
    assert child_payload["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    assert Path(summary["plan_json"]).exists()
    assert Path(summary["manifest_json"]).exists()
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["status"] == "planned"
    assert summary["executed_count"] == 0


def test_testbed_launcher_materializes_flow_child_configs_without_executing(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_k_sensitivity"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                "execute = false",
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.variant.overlay.simulation]",
                'name = "flow_low_k"',
                "",
                "[testbed.variant.overlay.flow.param.K.field]",
                'value = "5e-6 m/s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    generated = Path(summary["generated_configs_dir"]) / "low_k.toml"
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "simulation"
    assert "testbed" not in child_payload
    assert child_payload["simulation"]["name"] == "flow_low_k"
    assert child_payload["flow"]["param"]["K"]["field"]["value"] == "5e-6 m/s"
    assert summary["executed_count"] == 0


def test_testbed_launcher_expands_catalog_variants_without_execution(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    catalog_path = tmp_path / "variant_catalog.jsonl"
    catalog_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=True)
            for row in [
                {
                    "case_id": "catalog_coarse",
                    "title": "Catalog coarse",
                    "scale": "resolution",
                    "tier": "smoke",
                    "workspace_root": "workspaces/catalog_coarse",
                    "global_size": 400.0,
                    "tags": ["mesh_ready", "catalog"],
                    "enabled": True,
                },
                {
                    "case_id": "catalog_disabled",
                    "title": "Catalog disabled",
                    "scale": "resolution",
                    "tier": "smoke",
                    "workspace_root": "workspaces/catalog_disabled",
                    "global_size": 200.0,
                    "tags": ["mesh_ready", "catalog"],
                    "enabled": False,
                },
                {
                    "case_id": "catalog_other_tier",
                    "title": "Catalog other tier",
                    "scale": "resolution",
                    "tier": "full",
                    "workspace_root": "workspaces/catalog_other_tier",
                    "global_size": 100.0,
                    "tags": ["mesh_ready", "catalog"],
                    "enabled": True,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "catalog_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "catalog_mesh_resolution"',
                'subject = "mesh"',
                'base_config = "mesh_base.toml"',
                'output_root = "outputs/testbed"',
                "execute = false",
                "",
                "[testbed.catalog]",
                'path = "variant_catalog.jsonl"',
                'format = "jsonl"',
                'id_field = "case_id"',
                'label_field = "title"',
                'axis_field = "scale"',
                'tags_field = "tags"',
                'path_fields = ["workspace_root"]',
                'field_equals = { tier = "smoke" }',
                'tags = ["mesh_ready"]',
                "",
                "[[testbed.variant_from_catalog]]",
                'required_fields = ["workspace_root", "global_size"]',
                "",
                "[testbed.variant_from_catalog.overlay.workspace]",
                'project_root = "{workspace_root}"',
                "",
                "[testbed.variant_from_catalog.overlay.mesh_catchment.zone_meshing]",
                'global_size = "{global_size}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    assert summary["variant_count"] == 1
    generated = Path(summary["generated_configs_dir"]) / "catalog_coarse.toml"
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "simulation"
    assert "testbed" not in child_payload
    assert child_payload["simulation"]["process"] == [
        {"id": "mesh_main", "type": "mesh", "backend": "catchment"}
    ]
    assert child_payload["mesh_catchment"]["constraints_mode"] == "rivers_only"
    assert child_payload["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    assert Path(summary["plan_json"]).exists()
    assert Path(summary["manifest_json"]).exists()
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["status"] == "planned"
    assert summary["executed_count"] == 0
    assert child_payload["workspace"]["project_root"].endswith("workspaces/catalog_coarse")
    assert child_payload["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["variant_id"] == "catalog_coarse"
    assert rows[0]["variant_label"] == "Catalog coarse"
    assert rows[0]["axis"] == "resolution"


def test_testbed_launcher_materializes_comparison_child_configs_without_executing(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "comparison_base.toml"
    _write_comparison_base(base_config)
    config_path = tmp_path / "comparison_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "comparison_campaign"',
                'subject = "flow"',
                'base_config = "comparison_base.toml"',
                'output_root = "outputs/testbed"',
                "execute = false",
                "",
                "[testbed.runner]",
                'type = "comparison"',
                "",
                "[[testbed.variant]]",
                'id = "mf6_vs_bouss"',
                'axis = "method_pair"',
                "",
                "[testbed.variant.overlay.comparison]",
                'comparison_id = "mf6_vs_bouss"',
                'output_root = "comparison_outputs/mf6_vs_bouss"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    generated = Path(summary["generated_configs_dir"]) / "mf6_vs_bouss.toml"
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "comparison"
    assert "testbed" not in child_payload
    assert child_payload["comparison"]["comparison_id"] == "mf6_vs_bouss"
    assert child_payload["comparison"]["simulation"][0]["id"] == "reference"
    assert summary["executed_count"] == 0


def test_testbed_launcher_runs_comparison_variants_and_collects_metrics(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "comparison_base.toml"
    _write_comparison_base(base_config)
    config_path = tmp_path / "comparison_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "comparison_campaign"',
                'subject = "flow"',
                'base_config = "comparison_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "comparison"',
                "",
                "[[testbed.variant]]",
                'id = "candidate"',
                'axis = "method_pair"',
                "",
                "[testbed.variant.overlay.comparison]",
                'comparison_id = "candidate_comparison"',
                "",
                "[[testbed.metric]]",
                'name = "comparison_id"',
                "",
                "[[testbed.metric]]",
                'name = "n_metric_rows"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            raise AssertionError("simulation runner should not be used")

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            return {
                "comparison_id": payload["comparison"]["comparison_id"],
                "n_metric_rows": 3,
                "web_index": str(child_config.with_suffix(".html")),
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 1
    assert summary["successful_count"] == 1
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "variant_id,variant_label,axis,status,comparison_id,n_metric_rows" in metrics_text
    assert "candidate,candidate,method_pair,ok,candidate_comparison,3" in metrics_text


def test_testbed_launcher_runs_catalog_backed_comparison_variants(
    tmp_path: Path,
) -> None:
    flow_base = tmp_path / "flow_base.toml"
    _write_flow_base(flow_base)
    base_config = tmp_path / "comparison_base.toml"
    base_config.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "comparison_base"',
                'base_simulation_config = "flow_base.toml"',
                'output_root = "comparison_outputs/base"',
                "",
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6"',
                'solver = "modflow6"',
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
    catalog_path = tmp_path / "sites.csv"
    catalog_path.write_text(
        "\n".join(
            [
                "site_id,site_label,area_class,x_outlet,y_outlet,target_area_km2,tags,enabled",
                "site_01,Site 01,10km2,131189.1,6833784.4,10.0,natural;comparison,true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "comparison_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "natural_comparison_catalog"',
                'subject = "flow"',
                'base_config = "comparison_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "comparison"',
                "",
                "[testbed.catalog]",
                'path = "sites.csv"',
                'id_field = "site_id"',
                'label_field = "site_label"',
                'axis_field = "area_class"',
                'tags_field = "tags"',
                'tags = ["natural", "comparison"]',
                "",
                "[[testbed.variant_from_catalog]]",
                'required_fields = ["x_outlet", "y_outlet", "target_area_km2"]',
                'id_template = "{site_id}"',
                'label_template = "{site_label}"',
                'axis_template = "{area_class}"',
                "",
                "[testbed.variant_from_catalog.overlay.comparison]",
                'comparison_id = "{site_id}_mf6_bouss"',
                'output_root = "outputs/comparisons/{site_id}"',
                "",
                "[testbed.variant_from_catalog.overlay.comparison.base_simulation_overlay.geographic]",
                'x_outlet = "{x_outlet}"',
                'y_outlet = "{y_outlet}"',
                'target_area_km2 = "{target_area_km2}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            raise AssertionError("simulation runner should not be used")

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            return {
                "comparison_id": payload["comparison"]["comparison_id"],
                "comparison_root": payload["comparison"]["output_root"],
                "comparison_web_report": str(child_config.with_suffix(".html")),
                "audit_status": "pass",
                "n_metric_rows": 3,
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 1
    generated = Path(summary["generated_configs_dir"]) / "site_01.toml"
    generated_text = generated.read_text(encoding="utf-8")
    assert "# Stable identifier for this comparison run." in generated_text
    assert "# Shared TOML overlay applied to the base simulation config" in generated_text
    assert "# X coordinate of the watershed outlet" in generated_text
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "comparison"
    assert child_payload["comparison"]["comparison_id"] == "site_01_mf6_bouss"
    assert child_payload["comparison"]["base_simulation_config"] == flow_base.resolve().as_posix()
    geographic = child_payload["comparison"]["base_simulation_overlay"]["geographic"]
    assert geographic["x_outlet"] == 131189.1
    assert geographic["y_outlet"] == 6833784.4
    assert geographic["target_area_km2"] == 10.0
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["comparison_id"] == "site_01_mf6_bouss"
    assert rows[0]["comparison_web_report"].endswith("site_01.html")
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert (
        "variant_id,variant_label,axis,status,comparison_id,audit_status,"
        "n_metric_rows,n_difference_rows"
    ) in metrics_text
    assert "site_01,Site 01,10km2,ok,site_01_mf6_bouss,pass,3," in metrics_text


def test_testbed_launcher_runs_mesh_variants_and_collects_metrics(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[workspace]",
                'project_root = "mesh_outputs/base"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "rivers_only"',
                "",
                "[testbed]",
                'id = "mesh_resolution"',
                'output_root = "outputs/testbed"',
                "",
                "[[testbed.variant]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.variant.overlay.mesh_catchment.zone_meshing]",
                "global_size = 400.0",
                "",
                "[[testbed.variant]]",
                'id = "fine"',
                'axis = "resolution"',
                "",
                "[testbed.variant.overlay.mesh_catchment.zone_meshing]",
                "global_size = 100.0",
                "",
                "[[testbed.metric]]",
                'name = "n_cells"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            assert payload["workflow"] == "simulation"
            assert payload["simulation"]["process"][0]["type"] == "mesh"
            size = payload["mesh_catchment"]["zone_meshing"]["global_size"]
            n_cells = 10 if size == 400.0 else 40
            return {
                "summary_schema_version": "zone_conformal_sidecar_v1",
                "n_cells": n_cells,
                "output_mesh": str(child_config.with_suffix(".msh")),
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 2
    assert summary["successful_count"] == 2
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "variant_id,variant_label,axis,status,n_cells" in metrics_text
    assert "coarse,coarse,resolution,ok,10" in metrics_text
    assert "fine,fine,resolution,ok,40" in metrics_text
    manifest = json.loads(Path(summary["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "testbed_manifest_v1"
    assert manifest["successful_count"] == 2


def test_testbed_launcher_runs_flow_variants_and_collects_metrics(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_k_sensitivity"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.variant.overlay.simulation]",
                'name = "flow_low_k"',
                "",
                "[testbed.variant.overlay.flow.param.K.field]",
                'value = "5e-6 m/s"',
                "",
                "[[testbed.variant]]",
                'id = "high_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.variant.overlay.simulation]",
                'name = "flow_high_k"',
                "",
                "[testbed.variant.overlay.flow.param.K.field]",
                'value = "2e-5 m/s"',
                "",
                "[[testbed.metric]]",
                'name = "sim_id"',
                "",
                "[[testbed.metric]]",
                'name = "k_value"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[Path, bool]] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            calls.append((child_config, no_display))
            payload = load_toml_with_base_config(child_config)
            run_name = payload["simulation"]["name"]
            k_value = payload["flow"]["param"]["K"]["field"]["value"]
            return {
                "name": run_name,
                "sim_id": f"sim_{run_name}",
                "k_value": k_value,
                "wall_time_seconds": 1.25,
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 2
    assert all(no_display for _, no_display in calls)
    assert summary["successful_count"] == 2
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "variant_id,variant_label,axis,status,sim_id,k_value" in metrics_text
    assert "low_k,low_k,hydraulic_conductivity,ok,sim_flow_low_k,5e-6 m/s" in metrics_text
    assert "high_k,high_k,hydraulic_conductivity,ok,sim_flow_high_k,2e-5 m/s" in metrics_text
    cases_text = Path(summary["cases_csv"]).read_text(encoding="utf-8")
    assert "flow_low_k" in cases_text
    assert "sim_flow_high_k" in cases_text


def test_flow_testbed_enriches_metrics_from_simulation_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_catalog_metrics"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "reference"',
                'axis = "catalog"',
                "",
                "[testbed.variant.overlay.simulation]",
                'name = "flow_reference"',
                "",
                "[[testbed.metric]]",
                'name = "duration_s"',
                'source = "flow_metrics.duration_s"',
                "",
                "[[testbed.metric]]",
                'name = "param_K"',
                'source = "flow_metrics.param_K"',
                "",
                "[[testbed.metric]]",
                'name = "max_abs_balance_error"',
                'source = "flow_metrics.max_abs_mass_balance_percent_error"',
                "",
                "[[testbed.metric]]",
                'name = "head_range_m"',
                'source = "flow_metrics.head_range_m"',
                "",
                "[[testbed.metric]]",
                'name = "prescribed_head_out"',
                'source = "flow_metrics.budget_chd_total_out"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            return {
                "name": "flow_reference",
                "sim_id": "11111111-1111-1111-1111-111111111111",
            }

    class _FakeRun:
        sim_id = "11111111-1111-1111-1111-111111111111"
        name = "flow_reference"
        project = "testbed"
        solver = "modflow6"
        solver_category = "distributed"
        flow_regime = "steady"
        status = "completed"
        duration_s = 12.5
        n_cells = 4
        n_layers = 1
        n_timesteps = 2

        @property
        def parameters(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "param_name": "K",
                        "zone_id": "__global__",
                        "value": 1.0e-5,
                        "unit": "m/s",
                    }
                ]
            )

        @property
        def mass_balance(self) -> pd.DataFrame:
            return pd.DataFrame({"percent_error": [0.1, -0.25]})

        def budget(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"component": "chd", "flux_in": 0.0, "flux_out": 1.2},
                    {"component": "chd", "flux_in": 0.0, "flux_out": 1.8},
                    {"component": "rcha", "flux_in": 3.0, "flux_out": 0.0},
                ]
            )

        def has_field(self, variable: str) -> bool:
            return variable in {"head", "outflow_drain"}

        def field(self, variable: str, timestep: int = -1) -> np.ndarray:
            assert timestep == -1
            if variable == "head":
                return np.array([10.0, 12.0, np.nan, 14.0])
            return np.array([0.0, 2.0, 0.5, np.nan])

    class _FakeStore:
        closed = False

        def __getitem__(self, sim_id: str) -> _FakeRun:
            assert sim_id == _FakeRun.sim_id
            return _FakeRun()

        def close(self) -> None:
            self.closed = True

    fake_store = _FakeStore()

    def _fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[_FakeStore, str]:
        assert config_path is not None
        assert preferred_sim_id == _FakeRun.sim_id
        assert preferred_name == "flow_reference"
        return fake_store, _FakeRun.sim_id

    register_testbed_runner_provider(_FakeProvider())
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.runtime.metadata.discover_result_store",
        _fake_discover_result_store,
    )

    summary = MethodTestbedLauncher(config_path).run()

    assert fake_store.closed is True
    assert summary["successful_count"] == 1
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert (
        "variant_id,variant_label,axis,status,duration_s,param_K,"
        "max_abs_balance_error,head_range_m,prescribed_head_out"
    ) in metrics_text
    assert "reference,reference,catalog,ok,12.5,1e-05,0.25,4.0,3.0" in metrics_text
    manifest = json.loads(Path(summary["manifest_json"]).read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    assert case["flow_metrics"]["n_cells"] == 4
    assert case["catalog"]["status"] == "completed"


def test_testbed_required_metric_failure_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_required_metric"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "continue_on_error = false",
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.variant]]",
                'id = "reference"',
                'axis = "catalog"',
                "",
                "[testbed.variant.overlay.simulation]",
                'name = "flow_reference"',
                "",
                "[[testbed.metric]]",
                'name = "missing_required_metric"',
                'source = "flow_metrics.missing_required_metric"',
                "required = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            return {"name": "flow_reference", "sim_id": "missing-catalog-run"}

    def _fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[None, str]:
        assert config_path is not None
        assert preferred_sim_id == "missing-catalog-run"
        assert preferred_name == "flow_reference"
        return None, ""

    register_testbed_runner_provider(_FakeProvider())
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.runtime.metadata.discover_result_store",
        _fake_discover_result_store,
    )

    with pytest.raises(ValueError, match="Required testbed metric"):
        MethodTestbedLauncher(config_path).run()

    manifest_path = tmp_path / "outputs" / "testbed" / "testbed_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["failed_count"] == 1
    assert "Required testbed metric" in manifest["cases"][0]["error"]
