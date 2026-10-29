"""A site selection file is planned, or runs as a plan or as a selection of delineated catchments."""

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
from hydromodpy.spatial.site_selection.config.site_selection_config import OutputConfig
from hydromodpy.workflow.site_selection.catchments_csv import select_delineated_catchments_from_csv
from hydromodpy.workflow.site_selection.selection_plan import plan_site_selection
from hydromodpy.workflow.site_selection.selection_run import run_site_selection
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


PLANNED = {
    "write_rejected": "rejected", "write_selected": "selected", "write_geojson": "geojson",
    "write_geoparquet": "geoparquet", "write_geopackage": "geopackage", "write_csv": "csv",
    "write_report_html": "report_html",
}  # fmt: skip


@pytest.mark.parametrize("switch", [False, True], ids=["defaults", "all_outputs"])
def test_the_plan_resolves_paths_and_lists_the_switched_outputs(tmp_path, switch):
    output = {key: True for key in PLANNED} if switch else {}
    section = selection_section(output_root="outputs/demo", output=output)

    plan = plan_site_selection(write_selection_toml(tmp_path, section))

    assert plan.config.output_root == tmp_path / "outputs/demo"
    assert plan.manifest["strategy"]["effective_profile"] == "area_only"
    assert plan.manifest["criteria"]["area_mode"] == "hard_reject"
    defaults = OutputConfig()
    expected = [name for key, name in PLANNED.items() if switch or getattr(defaults, key)]
    assert plan.manifest["planned_outputs"] == expected
    if not switch:  # the documented defaults, written out
        assert "selected" in expected
        assert not {"geoparquet", "report_html"} & set(expected)


def test_the_plan_writes_its_manifest(tmp_path):
    plan = plan_site_selection(write_selection_toml(tmp_path, selection_section("gauged")))

    payload = json.loads(plan.write_manifest().read_text(encoding="utf-8"))

    assert payload["selection_id"] == "demo"
    assert payload["strategy"]["candidate_mode"] == "station_outlets"
    assert payload["strategy"]["effective_profile"] == "gauged_downstream_station"
    assert (tmp_path / "out" / "site_selection_plan.json").is_file()


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
    counts = manifest["counts"]
    assert (manifest["selection_id"], counts["selected"], counts["rejected"]) == ("demo", 1, 1)
    expected = {
        "selected_sites_csv": "selected_sites.csv", "site_selection_report_html": "review/index.html",
        "site_selection_map_png": "review/site_selection_map.png",
    }  # fmt: skip
    assert {key: manifest["outputs"][key] for key in expected} == expected
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
    write_vector_layer(tmp_path / "geology.gpkg", [box(X93, Y93, X93 + 99, Y93 + 99)], unit=["schist"])  # fmt: skip
    write_vector_layer(tmp_path / "pz.gpkg", [Point(X93 + 10.0, Y93 + 10.0)], id=["PZ001"])
    area = {"mode": "hard_reject", "hard_min_area_km2": 0.001, "hard_max_area_km2": 1.0}
    geology = {"layers": [{"name": "BRGM", "path": "geology.gpkg", "class_field": "unit"}]}
    piezometers = [{"name": "BSS", "path": "pz.gpkg", "id_field": "id"}]
    criteria = {
        "area": area,
        "geology": geology,
        "observations": {"piezometer_layers": piezometers},
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
