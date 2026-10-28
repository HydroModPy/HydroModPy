"""A site selection file runs as a plan or as a selection of delineated catchments."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.reporting.site_selection.plan import render_site_selection_plan_html_report
from hydromodpy.schema.site_selection_manifest import SITE_SELECTION_MANIFEST_NAME
from hydromodpy.spatial.site_selection.runner import (
    run_site_selection,
    select_delineated_catchments_from_csv,
)
from tests._helpers.site_selection_cases import (
    X93,
    Y93,
    selection_section,
    write_basin,
    write_selection_toml,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

HTML = {"write_report_html": True}
CATCHMENTS = {"mode": "delineated_catchments", "catchments_csv": "catchments.csv"}


def _write(tmp_path, *, catchments: str = "site_ok,0,0,100\nsite_bad,1,1,50", **tables):
    (tmp_path / "catchments.csv").write_text(f"site_id,x,y,area_km2,watershed_shp\n{catchments}\n")
    return write_selection_toml(tmp_path, selection_section(**tables))


def test_the_plan_mode_writes_the_plan_manifest_and_its_report(tmp_path):
    config = _write(tmp_path, input={"mode": "plan_only"}, output=HTML)

    run = run_site_selection(config, plan_report_renderer=render_site_selection_plan_html_report)

    assert (run.action, run.selection_id) == ("plan", "demo")
    assert run.outputs["plan_manifest"] == tmp_path / "out" / "site_selection_plan.json"
    html = run.outputs["site_selection_report_html"].read_text(encoding="utf-8")
    assert "site selection plan" in html
    assert "No site is selected or rejected" in html


def test_delineated_catchments_are_selected_with_their_manifest_and_report(tmp_path):
    config = _write(tmp_path, input={**CATCHMENTS, "region_id": "BZH"}, output=HTML)

    run = run_site_selection(config, report_renderer=render_site_selection_html_report)

    assert (run.action, run.counts) == ("delineated_catchments", {"selected": 1, "rejected": 1})
    outputs = run.outputs
    assert outputs["site_selection_manifest_json"].name == SITE_SELECTION_MANIFEST_NAME
    manifest = json.loads(outputs["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert (manifest["selection_id"], manifest["counts"]["selected"]) == ("demo", 1)
    assert manifest["counts"]["rejected"] == 1
    assert {
        key: manifest["outputs"][key]
        for key in ("selected_sites_csv", "site_selection_report_html", "site_selection_map_png")
    } == {  # fmt: skip
        "selected_sites_csv": "selected_sites.csv",
        "site_selection_report_html": "review/index.html",
        "site_selection_map_png": "review/site_selection_map.png",
    }
    html = outputs["site_selection_report_html"].read_text(encoding="utf-8")
    for text in ("site_ok", "site_bad", "Control map", 'src="data:image/png;base64,',
                 "Rejected sites", 'data-block-group="selection-map"'):  # fmt: skip
        assert text in html
    for level in ("compact", "standard", "audit"):
        assert f'data-target-level="{level}"' in html
        assert (outputs["site_selection_report_html"].parent / level / "index.html").is_file()


def test_without_a_renderer_no_report_is_written(tmp_path):
    run = run_site_selection(_write(tmp_path, input=CATCHMENTS, output=HTML))

    assert run.outputs["site_selection_manifest_json"].is_file()
    assert "site_selection_report_html" not in run.outputs
    assert not (tmp_path / "out" / "review" / "index.html").exists()


@pytest.mark.parametrize(
    ("top", "output", "error", "match"),
    [
        ({"workflow": {"mode": "site_selection"}}, {}, ConfigError, "hmp site select"),
        (
            {},
            {"write_regional_lab_csv": True},
            ValueError,
            "write_regional_lab_csv.*--into-catalog",
        ),
    ],
)
def test_a_retired_switch_is_refused_by_name(tmp_path, top, output, error, match):
    section = selection_section(input={"mode": "plan_only"}, output=output)

    with pytest.raises(error, match=match):
        run_site_selection(write_selection_toml(tmp_path, section, **top))


def test_configured_geology_and_piezometer_layers_are_written_with_the_selection(tmp_path):
    basin = write_basin(tmp_path)
    write_vector_layer(
        tmp_path / "geology.gpkg", [box(X93, Y93, X93 + 99, Y93 + 99)], unit=["schist"]
    )
    write_vector_layer(tmp_path / "pz.gpkg", [Point(X93 + 10.0, Y93 + 10.0)], id=["PZ001"])
    area = {"mode": "hard_reject", "hard_min_area_km2": 0.001, "hard_max_area_km2": 1.0}
    criteria = {
        "area": area,
        "geology": {"layers": [{"name": "BRGM", "path": "geology.gpkg", "class_field": "unit"}]},
        "observations": {
            "piezometer_layers": [{"name": "BSS", "path": "pz.gpkg", "id_field": "id"}]
        },
    }
    config = _write(
        tmp_path, criteria=criteria, output={"write_geopackage": True},
        catchments=f"site_001,{X93},{Y93},0.01,{Path(basin).name}",
    )  # fmt: skip

    result, paths = select_delineated_catchments_from_csv(
        config_path=config, catchments_csv=tmp_path / "catchments.csv"
    )

    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    for key in ("geology_evidence_jsonl", "geology_basins_geojson", "piezometer_evidence_jsonl",
                "observation_evidence_jsonl", "site_selection_evidence_jsonl",
                "observation_points_geojson"):  # fmt: skip
        assert paths[key].is_file()
    layers = set(gpd.list_layers(paths["site_selection_gpkg"])["name"])
    assert {"geology_basins", "observation_points"} <= layers
