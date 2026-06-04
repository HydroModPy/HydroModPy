from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.analysis.testbed.config import TestbedConfig as MethodTestbedConfig
from hydromodpy.analysis.testbed.runtime import TestbedLauncher as MethodTestbedLauncher
from hydromodpy.core.toml_io import load_toml_with_base_config

from ._testbed_builders import _write_flow_base, _write_mesh_base


def test_testbed_config_parses_mesh_cases(tmp_path: Path) -> None:
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
                "[[testbed.case]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.case.overlay.mesh_catchment.zone_meshing]",
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
    assert cfg.cases is cfg.case
    assert cfg.cases[0].overlay["mesh_catchment"]["zone_meshing"]["global_size"] == 400.0
    assert cfg.metrics[0].source == "n_cells"


def test_testbed_config_parses_flow_cases(tmp_path: Path) -> None:
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
                "[[testbed.case]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.case.overlay.flow.param.K.field]",
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
    assert cfg.cases[0].overlay["flow"]["param"]["K"]["field"]["value"] == "5e-6 m/s"


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
                "[[testbed.case]]",
                'id = "baseline"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires testbed.base_config"):
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


def test_testbed_config_rejects_legacy_python_variant_field_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TestbedConfig.variants is no longer supported"):
        MethodTestbedConfig(
            config_path=tmp_path / "testbed.toml",
            base_dir=tmp_path,
            id="direct_config",
            profile="generic",
            subject="mesh",
            purpose="robustness",
            output_root=tmp_path / "outputs",
            runner={"type": "simulation"},
            variants=[{"id": "coarse", "label": "Coarse"}],
        )

    with pytest.raises(
        ValueError,
        match="TestbedConfig.catalog_variants is no longer supported",
    ):
        MethodTestbedConfig(
            config_path=tmp_path / "testbed.toml",
            base_dir=tmp_path,
            id="direct_config",
            profile="generic",
            subject="mesh",
            purpose="robustness",
            output_root=tmp_path / "outputs",
            runner={"type": "simulation"},
            catalog_variants=[{"id_template": "{case_id}"}],
        )


_MESH_BASE_CATALOG_CSV = "\n".join(
    [
        "case_id,title",
        "catalog_coarse,Catalog coarse",
    ]
)

_CASE_CATALOG_CSV = "\n".join(
    [
        "case_id,title,global_size",
        "catalog_coarse,Catalog coarse,400.0",
    ]
)

_REJECTS_LEGACY_CASES = {
    "test_testbed_config_rejects_legacy_variants_alias": {
        "extra_files": {},
        "body": [
            '[workflow]\nmode = "testbed"',
            "",
            "[testbed]",
            'id = "mesh_resolution"',
            'subject = "mesh"',
            'base_config = "mesh_base.toml"',
            "",
            "[[testbed.variants]]",
            'id = "coarse"',
        ],
        "match": "testbed.case or testbed.case_from_catalog must contain at least one item",
    },
    "test_testbed_config_rejects_mixed_case_and_variant_spellings": {
        "extra_files": {},
        "body": [
            '[workflow]\nmode = "testbed"',
            "",
            "[testbed]",
            'id = "mesh_resolution"',
            'subject = "mesh"',
            'base_config = "mesh_base.toml"',
            "",
            "[[testbed.case]]",
            'id = "coarse"',
            "",
            "[[testbed.variant]]",
            'id = "fine"',
        ],
        "match": "testbed.variant is no longer supported",
    },
    "test_testbed_config_rejects_legacy_variant_spelling": {
        "extra_files": {},
        "body": [
            '[workflow]\nmode = "testbed"',
            "",
            "[testbed]",
            'id = "mesh_resolution"',
            'subject = "mesh"',
            'base_config = "mesh_base.toml"',
            "",
            "[[testbed.variant]]",
            'id = "coarse"',
            "",
            "[testbed.variant.overlay.mesh_catchment.zone_meshing]",
            "global_size = 400.0",
        ],
        "match": "testbed.variant is no longer supported",
    },
    "test_testbed_config_rejects_removed_mesh_catchment_runner": {
        "extra_files": {},
        "body": [
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
            "[[testbed.case]]",
            'id = "coarse"',
        ],
        "match": "Unsupported testbed.runner.type 'mesh_catchment'",
    },
    "test_testbed_config_rejects_legacy_catalog_variant_alias": {
        "extra_files": {"variant_catalog.csv": _MESH_BASE_CATALOG_CSV},
        "body": [
            '[workflow]\nmode = "testbed"',
            "",
            "[testbed]",
            'id = "catalog_mesh_resolution"',
            'subject = "mesh"',
            'base_config = "mesh_base.toml"',
            "execute = false",
            "",
            "[testbed.catalog]",
            'path = "variant_catalog.csv"',
            'id_field = "case_id"',
            'label_field = "title"',
            "",
            "[[testbed.catalog_variant]]",
            'id_template = "{case_id}"',
        ],
        "match": "testbed.case or testbed.case_from_catalog must contain at least one item",
    },
    "test_testbed_config_rejects_legacy_variant_from_catalog_spelling": {
        "extra_files": {"case_catalog.csv": _CASE_CATALOG_CSV},
        "body": [
            '[workflow]\nmode = "testbed"',
            "",
            "[testbed]",
            'id = "catalog_mesh_resolution"',
            'subject = "mesh"',
            'base_config = "mesh_base.toml"',
            "execute = false",
            "",
            "[testbed.catalog]",
            'path = "case_catalog.csv"',
            'id_field = "case_id"',
            'label_field = "title"',
            "",
            "[[testbed.variant_from_catalog]]",
            'required_fields = ["global_size"]',
            "",
            "[testbed.variant_from_catalog.overlay.mesh_catchment.zone_meshing]",
            'global_size = "{global_size}"',
        ],
        "match": "testbed.variant_from_catalog is no longer supported",
    },
}


@pytest.mark.parametrize(
    ("body", "extra_files", "match"),
    [
        pytest.param(case["body"], case["extra_files"], case["match"], id=name)
        for name, case in _REJECTS_LEGACY_CASES.items()
    ],
)
def test_testbed_config_rejects_legacy(
    tmp_path: Path,
    body: list[str],
    extra_files: dict[str, str],
    match: str,
) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    for filename, content in extra_files.items():
        (tmp_path / filename).write_text(content + "\n", encoding="utf-8")
    config_path = tmp_path / "testbed.toml"
    config_path.write_text("\n".join(body) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        MethodTestbedConfig.from_file(config_path)


def test_testbed_catalog_can_resolve_site_selection_manifest(tmp_path: Path) -> None:
    base_config = tmp_path / "mesh_base.toml"
    _write_mesh_base(base_config)
    selection_root = tmp_path / "site_selection_outputs"
    selection_root.mkdir()
    catalog_path = selection_root / "regional_lab_sites.csv"
    catalog_path.write_text(
        "\n".join(
            [
                "site_id,site_label,region_id,x_outlet,y_outlet,area_km2,tags,enabled",
                "site_01,Site 01,aura,131189.1,6833784.4,45.5,selected;comparison,true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = selection_root / "site_selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "site_selection_manifest_v1",
                "selection_id": "aura_area_only_v1",
                "output_root": str(selection_root),
                "outputs": {
                    "regional_lab_sites_csv": "regional_lab_sites.csv",
                    "selected_sites_csv": "selected_sites.csv",
                },
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "catalog_from_selection_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "site_selection_catalog"',
                'subject = "mesh"',
                'base_config = "mesh_base.toml"',
                'output_root = "outputs/testbed"',
                "execute = false",
                "",
                "[testbed.catalog]",
                'from_site_selection_manifest = "site_selection_outputs/site_selection_manifest.json"',
                'output = "regional_lab_sites_csv"',
                'id_field = "site_id"',
                'label_field = "site_label"',
                'axis_field = "region_id"',
                'tags_field = "tags"',
                'tags = ["comparison"]',
                "",
                "[[testbed.case_from_catalog]]",
                'required_fields = ["x_outlet", "y_outlet", "area_km2"]',
                'id_template = "{site_id}"',
                'label_template = "{site_label}"',
                'axis_template = "{region_id}"',
                "",
                "[testbed.case_from_catalog.overlay.workspace]",
                'project_root = "workspaces/{site_id}"',
                "",
                "[testbed.case_from_catalog.overlay.geographic.catchment]",
                'x_outlet = "{x_outlet}"',
                'y_outlet = "{y_outlet}"',
                'buff_area = "10%"',
                "",
                "[testbed.case_from_catalog.overlay.mesh_catchment.zone_meshing]",
                'global_size = "{area_km2}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = MethodTestbedConfig.from_file(config_path)
    assert cfg.catalog is not None
    assert cfg.catalog.path == catalog_path.resolve()
    assert cfg.catalog.source_manifest_path == manifest_path.resolve()
    assert cfg.catalog.source_manifest_output_key == "regional_lab_sites_csv"

    summary = MethodTestbedLauncher(config_path).run()

    assert summary["case_count"] == 1
    generated = Path(summary["generated_configs_dir"]) / "site_01.toml"
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workspace"]["project_root"].endswith("workspaces/site_01")
    assert child_payload["geographic"]["catchment"]["x_outlet"] == 131189.1
    assert child_payload["geographic"]["catchment"]["y_outlet"] == 6833784.4
    assert child_payload["geographic"]["catchment"]["buff_area"] == "10%"
    assert child_payload["mesh_catchment"]["zone_meshing"]["global_size"] == 45.5
    manifest = json.loads(Path(summary["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["site_catalog_path"] == str(catalog_path.resolve())
    assert manifest["catalog"]["path"] == str(catalog_path.resolve())
    assert manifest["catalog"]["source_manifest_path"] == str(manifest_path.resolve())
    assert manifest["catalog"]["source_manifest_output_key"] == "regional_lab_sites_csv"


def test_testbed_catalog_manifest_source_requires_requested_output(tmp_path: Path) -> None:
    selection_root = tmp_path / "site_selection_outputs"
    selection_root.mkdir()
    manifest_path = selection_root / "site_selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "site_selection_manifest_v1",
                "selection_id": "aura_area_only_v1",
                "output_root": str(selection_root),
                "outputs": {"selected_sites_csv": "selected_sites.csv"},
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "catalog_from_selection_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "site_selection_catalog"',
                "execute = false",
                "",
                "[testbed.catalog]",
                'from_site_selection_manifest = "site_selection_outputs/site_selection_manifest.json"',
                "",
                "[[testbed.case_from_catalog]]",
                'id_template = "{site_id}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not contain output 'regional_lab_sites_csv'"):
        MethodTestbedConfig.from_file(config_path)
