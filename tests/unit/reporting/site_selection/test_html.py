"""The site selection HTML report and its result blocks."""

from __future__ import annotations

import pytest

from hydromodpy.reporting.site_selection.blocks import build_site_selection_result_blocks
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.workflow.site_selection.selection_run import run_site_selection
from tests._helpers.site_selection_cases import selection_section, write_selection_toml

pytestmark = pytest.mark.fast


def test_the_report_can_be_rendered_again_to_another_file(tmp_path):
    (tmp_path / "catchments.csv").write_text("site_id,x,y,area_km2\nsite_ok,0,0,100\n")
    section = selection_section(
        input={"mode": "delineated_catchments", "catchments_csv": "catchments.csv"}
    )
    run = run_site_selection(write_selection_toml(tmp_path, section))

    custom = render_site_selection_html_report(
        run.outputs["site_selection_manifest_json"], output_path=tmp_path / "custom" / "report.html"
    )

    assert custom == tmp_path / "custom" / "report.html"
    assert "site_ok" in custom.read_text(encoding="utf-8")


def test_the_station_influence_block_lists_each_influenced_station(tmp_path):
    map_path = tmp_path / "map.png"
    map_path.write_bytes(b"fake")
    component = {
        "site_id": "site_001",
        "criterion_id": "station_influence",
        "criterion_family": "observations",
        "criterion_status": "warning",
        "raw_value": "general_influence",
        "reason": "station has general hydrologic influence metadata",
        "evidence_json": {
            "source_feature_id": "J123456701",
            "station_influence_status": "general_influence",
            "station_influence_flags": ["general_influence"],
            "matched_keywords": ["retenue"],
        },
    }
    manifest = dict.fromkeys(("counts", "territory", "criteria", "dem", "flow_products", "outputs"), {})  # fmt: skip
    manifest |= {
        "selection_id": "station_influence_report",
        "strategy": {"principle": "observation_led", "candidate_mode": "station_outlets"},
    }

    blocks = build_site_selection_result_blocks(
        manifest, manifest_path=tmp_path / "site_selection_manifest.json", output_root=tmp_path,
        map_path=map_path, selected=[], rejected=[], decisions=[], evidence=[],
        components=[component],
    )  # fmt: skip

    block = next(item for item in blocks if item.block_id == "station_influence")
    assert block.status == "available"
    row = block.tables[0].rows[0]
    assert (row["station_id"], row["decision"]) == ("J123456701", "general_influence")
    assert "no obstacle stands upstream" in block.warnings[0]
