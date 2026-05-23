from __future__ import annotations

import json

import pytest

from hydromodpy.spatial.site_selection.html_report import render_site_selection_html_report
from hydromodpy.spatial.site_selection.manifest import (
    MANIFEST_SCHEMA_VERSION,
    SITE_SELECTION_MANIFEST_NAME,
    validate_selection_manifest,
    write_selection_manifest,
)
from hydromodpy.workflow.site_selection import select_delineated_catchments_from_csv


@pytest.mark.fast
def test_selection_outputs_manifest_and_html_report(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "report_demo"',
                'output_root = "out"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x,y,area_km2",
                "site_ok,0,0,100",
                "site_bad,1,1,50",
            ]
        ),
        encoding="utf-8",
    )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        region_id="Bretagne",
    )

    assert len(result.selected) == 1
    assert paths["site_selection_manifest_json"].name == SITE_SELECTION_MANIFEST_NAME
    assert paths["site_selection_manifest_json"].is_file()
    assert paths["site_selection_report_html"].is_file()
    assert paths["site_selection_map_png"].is_file()

    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["selection_id"] == "report_demo"
    assert manifest["counts"]["selected"] == 1
    assert manifest["counts"]["rejected"] == 1
    assert manifest["outputs"]["selected_sites_csv"] == "selected_sites.csv"
    assert manifest["outputs"]["site_selection_report_html"] == "review/index.html"
    assert manifest["outputs"]["site_selection_map_png"] == "review/site_selection_map.png"

    html = paths["site_selection_report_html"].read_text(encoding="utf-8")
    assert "report_demo" in html
    assert "site_ok" in html
    assert "site_bad" in html
    assert "Carte de controle" in html
    assert 'src="data:image/png;base64,' in html
    assert "Sites rejetes" in html


@pytest.mark.fast
def test_render_site_selection_html_report_supports_custom_output(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "custom_report_demo"',
                'output_root = "out"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_ok,0,0,100\n", encoding="utf-8")
    _, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
    )

    custom_html = render_site_selection_html_report(
        paths["site_selection_manifest_json"],
        output_path=tmp_path / "custom" / "report.html",
    )

    assert custom_html == tmp_path / "custom" / "report.html"
    assert custom_html.is_file()


@pytest.mark.fast
def test_validate_selection_manifest_checks_schema_and_outputs(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "selection_decisions.jsonl").write_text("", encoding="utf-8")
    (root / "criteria_components.jsonl").write_text("", encoding="utf-8")
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "selection_id": "valid_demo",
        "action": "delineated_catchments",
        "output_root": str(root),
        "strategy": {},
        "territory": {},
        "input": {},
        "criteria": {},
        "counts": {},
        "outputs": {
            "selection_decisions_jsonl": "selection_decisions.jsonl",
            "criteria_components_jsonl": "criteria_components.jsonl",
            "site_selection_manifest_json": SITE_SELECTION_MANIFEST_NAME,
        },
        "flow_products": {},
    }
    write_selection_manifest(manifest_path, manifest)

    assert validate_selection_manifest(manifest_path) == []

    (root / "criteria_components.jsonl").unlink()
    errors = validate_selection_manifest(manifest_path)
    assert any("criteria_components_jsonl" in error for error in errors)


@pytest.mark.fast
def test_validate_selection_manifest_rejects_bad_schema_version(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    write_selection_manifest(
        manifest_path,
        {
            "schema_version": "bad",
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "selection_id": "bad_demo",
            "action": "delineated_catchments",
            "output_root": str(root),
            "strategy": {},
            "territory": {},
            "input": {},
            "criteria": {},
            "counts": {},
            "outputs": {},
        },
    )

    errors = validate_selection_manifest(manifest_path, check_outputs=False)
    assert any("unsupported schema_version" in error for error in errors)


@pytest.mark.fast
def test_validate_selection_manifest_rejects_invalid_geojson_artifact(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "selection_decisions.jsonl").write_text("", encoding="utf-8")
    (root / "criteria_components.jsonl").write_text("", encoding="utf-8")
    (root / "selected_outlets.geojson").write_text('{"type":"FeatureCollection"}', encoding="utf-8")
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    write_selection_manifest(
        manifest_path,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "selection_id": "bad_geojson_demo",
            "action": "delineated_catchments",
            "output_root": str(root),
            "strategy": {},
            "territory": {},
            "input": {},
            "criteria": {},
            "counts": {},
            "outputs": {
                "selection_decisions_jsonl": "selection_decisions.jsonl",
                "criteria_components_jsonl": "criteria_components.jsonl",
                "site_selection_manifest_json": SITE_SELECTION_MANIFEST_NAME,
                "selected_outlets_geojson": "selected_outlets.geojson",
            },
        },
    )

    errors = validate_selection_manifest(manifest_path)

    assert any("features must be a list" in error for error in errors)


@pytest.mark.fast
def test_validate_selection_manifest_rejects_invalid_png_artifact(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "selection_decisions.jsonl").write_text("", encoding="utf-8")
    (root / "criteria_components.jsonl").write_text("", encoding="utf-8")
    (root / "site_selection_map.png").write_bytes(b"not-a-png")
    manifest_path = root / SITE_SELECTION_MANIFEST_NAME
    write_selection_manifest(
        manifest_path,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "selection_id": "bad_png_demo",
            "action": "delineated_catchments",
            "output_root": str(root),
            "strategy": {},
            "territory": {},
            "input": {},
            "criteria": {},
            "counts": {},
            "outputs": {
                "selection_decisions_jsonl": "selection_decisions.jsonl",
                "criteria_components_jsonl": "criteria_components.jsonl",
                "site_selection_manifest_json": SITE_SELECTION_MANIFEST_NAME,
                "site_selection_map_png": "site_selection_map.png",
            },
        },
    )

    errors = validate_selection_manifest(manifest_path)

    assert any("invalid PNG" in error for error in errors)
