from __future__ import annotations

import json
from pathlib import Path


def write_regional_lab_config(
    tmp_path: Path,
    *,
    execute: bool = False,
    continue_on_error: bool = True,
    catalog_name: str = "site_catalog.csv",
    config_name: str = "regional_lab.toml",
) -> Path:
    config_path = tmp_path / config_name
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


def write_regional_lab_testbed_profile_config(
    tmp_path: Path,
    *,
    execute: bool = False,
    continue_on_error: bool = True,
    catalog_name: str = "site_catalog.csv",
    config_name: str = "regional_lab.toml",
) -> Path:
    config_path = write_regional_lab_config(
        tmp_path,
        execute=execute,
        continue_on_error=continue_on_error,
        catalog_name=catalog_name,
        config_name=config_name,
    )
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'profile = "regional_lab"',
                "",
                config_path.read_text(encoding="utf-8").rstrip(),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def write_csv_catalog(tmp_path: Path) -> Path:
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


def write_jsonl_catalog(tmp_path: Path) -> Path:
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


def write_planned_configs(tmp_path: Path) -> None:
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
                '[workflow]\nmode = "comparison"',
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
