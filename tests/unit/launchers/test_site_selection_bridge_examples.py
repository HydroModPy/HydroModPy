from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.testbed.catalog_variants import expand_catalog_variants
from hydromodpy.analysis.testbed.config import TestbedConfig as MethodTestbedConfig
from hydromodpy.analysis.testbed.regional_lab_catalog import load_site_catalog
from hydromodpy.analysis.testbed.regional_lab_config import (
    RegionalLabConfig,
)
from hydromodpy.analysis.testbed.regional_lab_planning import build_regional_lab_plan

EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "18_site_selection_to_testbed"
)


def test_site_selection_manifest_testbed_example_expands_catalog() -> None:
    config_path = EXAMPLE_ROOT / "site_selection_catalog_testbed.toml"

    cfg = MethodTestbedConfig.from_file(config_path)
    variants = expand_catalog_variants(
        catalog=cfg.catalog,
        rules=cfg.catalog_variants,
    )

    assert cfg.catalog is not None
    assert cfg.catalog.source_manifest_path == (
        EXAMPLE_ROOT / "fixtures" / "site_selection_manifest.json"
    ).resolve()
    assert cfg.catalog.path == (EXAMPLE_ROOT / "fixtures" / "regional_lab_sites.csv").resolve()
    assert [variant.id for variant in variants] == ["demo_site_01", "demo_site_02"]
    assert variants[0].overlay["geographic"]["x_outlet"] == 131189.1


def test_site_selection_manifest_regional_lab_example_builds_plan() -> None:
    config_path = EXAMPLE_ROOT / "site_selection_regional_lab.toml"

    cfg = RegionalLabConfig.from_file(config_path)
    sites = load_site_catalog(cfg.catalog)
    selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)

    assert cfg.catalog.source_manifest_path == (
        EXAMPLE_ROOT / "fixtures" / "site_selection_manifest.json"
    ).resolve()
    assert [site.site_id for site in selected_sites] == ["demo_site_01", "demo_site_02"]
    assert [case.recipe_id for case in planned_cases] == [
        "mesh_plan",
        "mesh_plan",
        "comparison_plan",
        "comparison_plan",
    ]
    assert skipped_cases == []
