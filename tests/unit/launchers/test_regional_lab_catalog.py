from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.analysis.catalog import (
    CatalogLoadSpec,
    CatalogRowSelector,
    load_catalog_rows,
    select_catalog_rows,
)
from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher
from hydromodpy.analysis.testbed.regional_lab_catalog import load_site_catalog
from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabConfig
from hydromodpy.analysis.testbed.regional_lab_planning import (
    build_regional_lab_plan,
)
from hydromodpy.analysis.testbed.regional_lab_reporting import build_plan_payload

from ._regional_lab_builders import (
    write_csv_catalog,
    write_jsonl_catalog,
    write_planned_configs,
    write_regional_lab_config,
)


def test_regional_lab_catalog_can_resolve_site_selection_manifest(tmp_path: Path) -> None:
    catalog_path = write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)
    manifest_path = tmp_path / "site_selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "site_selection_manifest_v1",
                "selection_id": "scan_headwater_100km2",
                "output_root": str(tmp_path),
                "outputs": {
                    "regional_lab_sites_csv": catalog_path.name,
                    "selected_sites_csv": "selected_sites.csv",
                },
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'path = "site_catalog.csv"',
            "\n".join(
                [
                    'from_site_selection_manifest = "site_selection_manifest.json"',
                    'output = "regional_lab_sites_csv"',
                ]
            ),
        ),
        encoding="utf-8",
    )

    cfg = RegionalLabConfig.from_file(config_path)
    assert cfg.catalog.path == catalog_path.resolve()
    assert cfg.catalog.source_manifest_path == manifest_path.resolve()
    assert cfg.catalog.source_manifest_output_key == "regional_lab_sites_csv"

    sites = load_site_catalog(cfg.catalog)
    selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)
    assert [site.site_id for site in selected_sites] == [
        "headwater_100km2_outlet_2",
        "headwater_100km2_outlet_3",
    ]
    payload = build_plan_payload(
        cfg=cfg,
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
    )
    assert payload["site_catalog_path"] == str(catalog_path.resolve())
    assert payload["catalog"]["source_manifest_path"] == str(manifest_path.resolve())
    assert payload["catalog"]["source_manifest_output_key"] == "regional_lab_sites_csv"

    summary = RegionalLabProfileLauncher(config_path).run()
    plan = json.loads(Path(summary["plan_path"]).read_text(encoding="utf-8"))
    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    markdown = Path(summary["summary_markdown"]).read_text(encoding="utf-8")
    assert plan["catalog"]["source_manifest_path"] == str(manifest_path.resolve())
    assert report["catalog"]["source_manifest_output_key"] == "regional_lab_sites_csv"
    assert f"Site-selection manifest: `{manifest_path.resolve()}`" in markdown


def test_regional_lab_catalog_manifest_source_requires_requested_output(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "site_selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "site_selection_manifest_v1",
                "selection_id": "scan_headwater_100km2",
                "output_root": str(tmp_path),
                "outputs": {"selected_sites_csv": "selected_sites.csv"},
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'path = "site_catalog.csv"',
            'from_site_selection_manifest = "site_selection_manifest.json"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not contain output 'regional_lab_sites_csv'"):
        RegionalLabConfig.from_file(config_path)


def test_regional_lab_supports_jsonl_catalog(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(
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
    write_jsonl_catalog(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)

    assert [site.site_id for site in sites] == ["site_a", "site_b"]
    assert sites[0].tags == ("mesh_ready", "backend_ready")
    assert sites[1].enabled is False


def test_regional_lab_supports_utf8_bom_csv_catalog(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
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
    write_planned_configs(tmp_path)

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)

    assert [site.site_id for site in sites] == ["headwater_100km2_outlet_2"]


def test_common_catalog_loader_handles_paths_tags_and_filters(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.csv"
    catalog_path.write_text(
        "\n".join(
            [
                "case_id,tier,tags,enabled,config_path",
                "case_a,smoke,mesh_ready;catalog,true,configs/a.toml",
                "case_b,smoke,catalog,false,configs/b.toml",
                "case_c,full,mesh_ready;catalog,true,configs/c.toml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = load_catalog_rows(
        CatalogLoadSpec(
            path=catalog_path,
            format="csv",
            required_fields=("case_id",),
            path_fields=("config_path",),
            tag_fields=("tags",),
            source_label="test catalog",
        )
    )
    selected = select_catalog_rows(
        rows,
        selector=CatalogRowSelector(
            field_equals=(("tier", "smoke"),),
            tags=("mesh_ready",),
            enabled_field="enabled",
        ),
    )

    assert [row.raw["case_id"] for row in selected] == ["case_a"]
    assert selected[0].tags == ("mesh_ready", "catalog")
    assert selected[0].resolved_paths["config_path"] == str(
        (tmp_path / "configs" / "a.toml").resolve()
    )
