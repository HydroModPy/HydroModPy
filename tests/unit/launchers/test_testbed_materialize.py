from __future__ import annotations

import csv
import json
from pathlib import Path

from hydromodpy.analysis.testbed.runtime import TestbedLauncher as MethodTestbedLauncher
from hydromodpy.config.hydromodpy_config import WorkflowConfig
from hydromodpy.core.toml_io import load_toml_with_base_config

from ._testbed_builders import _write_comparison_base, _write_flow_base, _write_mesh_base


def _assert_child_config_loads(payload: dict[str, object], mode: str) -> None:
    """The child's workflow section must be what the schema accepts.

    It was written as a bare string for a while, which reads fine in TOML and is
    rejected by the model, so the shape is asserted through WorkflowConfig rather
    than by comparing keys. The rest of the payload stays a fixture, deliberately
    too thin to validate as a whole config.
    """
    assert payload["workflow"] == {"mode": mode}
    assert WorkflowConfig.model_validate(payload["workflow"]).mode == mode


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
                "[[testbed.case]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.case.overlay.mesh_catchment.zone_meshing]",
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
    _assert_child_config_loads(child_payload, "simulation")
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
                "[[testbed.case]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.case.overlay.simulation]",
                'name = "flow_low_k"',
                "",
                "[testbed.case.overlay.flow.param.K.field]",
                'value = "5e-6 m/s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    generated = Path(summary["generated_configs_dir"]) / "low_k.toml"
    child_payload = load_toml_with_base_config(generated)
    _assert_child_config_loads(child_payload, "simulation")
    assert "testbed" not in child_payload
    assert child_payload["simulation"]["name"] == "flow_low_k"
    assert child_payload["flow"]["param"]["K"]["field"]["value"] == "5e-6 m/s"
    assert summary["executed_count"] == 0


def test_testbed_launcher_expands_catalog_cases_without_execution(
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
                "[[testbed.case_from_catalog]]",
                'required_fields = ["workspace_root", "global_size"]',
                "",
                "[testbed.case_from_catalog.overlay.workspace]",
                'project_root = "{workspace_root}"',
                "",
                "[testbed.case_from_catalog.overlay.mesh_catchment.zone_meshing]",
                'global_size = "{global_size}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodTestbedLauncher(config_path).run()

    assert summary["case_count"] == 1
    generated = Path(summary["generated_configs_dir"]) / "catalog_coarse.toml"
    child_payload = load_toml_with_base_config(generated)
    _assert_child_config_loads(child_payload, "simulation")
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
    assert rows[0]["case_id"] == "catalog_coarse"
    assert summary["executed_count"] == 0
    assert child_payload["workspace"]["project_root"].endswith("workspaces/catalog_coarse")
    assert child_payload["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert "variant_id" not in rows[0]
    assert "variant_label" not in rows[0]
    assert rows[0]["case_label"] == "Catalog coarse"
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
                "[[testbed.case]]",
                'id = "mf6_vs_bouss"',
                'axis = "method_pair"',
                "",
                "[testbed.case.overlay.comparison]",
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
    _assert_child_config_loads(child_payload, "comparison")
    assert "testbed" not in child_payload
    assert child_payload["comparison"]["comparison_id"] == "mf6_vs_bouss"
    assert child_payload["comparison"]["simulation"][0]["id"] == "reference"
    assert summary["executed_count"] == 0
