"""The site selection report: its control map, its HTML pages and its result blocks."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import box, shape

from hydromodpy.reporting.site_selection import figures
from hydromodpy.reporting.site_selection.blocks import build_site_selection_result_blocks
from hydromodpy.reporting.site_selection.figures import (
    _choose_display_bounds,
    _prefer_dem_extent_from_manifest,
    render_site_selection_map,
)
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.spatial.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionDecision
from hydromodpy.spatial.site_selection.outputs.geojson import write_observation_points_geojson
from hydromodpy.spatial.site_selection.outputs.manifest import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.site_selection_cases import (
    L93,
    X93,
    Y93,
    make_catchment,
    make_selection,
    selection_section,
    write_vector_layer,
)

pytestmark = pytest.mark.fast


def _evidence(observation_type: str, feature_id: str, x: float, y: float):
    location = {"provider_location": {"x": x, "y": y, "crs": "EPSG:2154"}}
    return ObservationEvidence(
        "site_selected", observation_type, "synthetic", feature_id, record_year_count=5.0,
        evidence_json=location,
    )  # fmt: skip


def _site(tmp_path, name: str, x0: float, x1: float, area_km2: float):
    basin = write_vector_layer(tmp_path / f"{name}.geojson", [box(x0, 0.0, x1, 4.0)])
    x = (x0 + x1) / 2
    return make_catchment(name, x=x, y=1.0, area_km2=area_km2, source="synthetic", watershed_shp=str(basin))  # fmt: skip


def test_a_synthetic_review_shows_basins_observations_and_the_control_map(tmp_path):
    rejection = SelectionDecision(
        site_id="site_rejected", selection_principle="criteria_crossing", selected=False,
        decision_stage="criteria", decision_reason="synthetic rejection", blocking_flags=["x"],
    )  # fmt: skip
    selected, rejected = _site(tmp_path, "site_selected", 0.0, 6.0, 24.0), _site(tmp_path, "site_rejected", 8.0, 13.0, 20.0)  # fmt: skip
    selection = make_selection([selected], [rejected], decisions=[rejection])
    area = {"mode": "hard_reject", "hard_min_area_km2": 10.0, "hard_max_area_km2": 30.0}
    section = selection_section(
        output_root=tmp_path / "out", territory={"mode": "bbox", "bbox": [0.0, 0.0, 13.0, 4.0]},
        criteria={"area": area}, output={"write_report_html": True},
    )  # fmt: skip
    config = SiteSelectionConfig.model_validate(section)

    paths = write_selection_result(config.output_root, selection, selection_id="review")
    evidence = [_evidence("flow_station", "J000000001", 2.5, 1.5), _evidence("piezometer", "PZ1", 4.5, 2.5)]  # fmt: skip
    observations_path = tmp_path / "observation_points.geojson"
    paths["observation_points_geojson"] = write_observation_points_geojson(
        observations_path, evidence
    )
    paths |= write_manifest_and_optional_report(
        config=config, selection=selection, output_paths=paths, action="synthetic_spatial_review",
        report_renderer=render_site_selection_html_report,
    )  # fmt: skip

    basins = json.loads(paths["selected_basins_geojson"].read_text(encoding="utf-8"))
    assert (basins["features"][0]["geometry"]["type"], basins["hydromodpy_skipped_basins"]) == ("Polygon", [])  # fmt: skip
    observations = json.loads(observations_path.read_text(encoding="utf-8"))["features"]
    assert {one["properties"]["observation_type"] for one in observations} == {"flow_station", "piezometer"}  # fmt: skip
    assert paths["site_selection_map_png"].stat().st_size > 20_000
    html = paths["site_selection_report_html"].read_text(encoding="utf-8")
    for text in ("site_selection_map.png", "Control map", "fixture or synthetic"):
        assert text in html
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["outputs"]["observation_points_geojson"] == str(observations_path)
    # The report can be rendered again, to another file.
    custom = tmp_path / "custom" / "report.html"
    assert render_site_selection_html_report(paths["site_selection_manifest_json"], output_path=custom) == custom  # fmt: skip
    assert "site_selected" in custom.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("dem_crs", "map_crs"),
    [(None, L93), ("EPSG:32630", "EPSG:32630"), ("", L93), ("broken", L93)],
    ids=["no-dem", "utm-dem", "dem-without-crs", "unreadable-dem"],
)
def test_the_control_map_draws_every_geojson_in_the_crs_of_the_map(
    tmp_path, monkeypatch, dem_crs, map_crs
):
    basin = write_vector_layer(tmp_path / "basin.gpkg", [box(X93, Y93, X93 + 100.0, Y93 + 100.0)])
    selection = make_selection([make_catchment(x=X93, y=Y93, watershed_shp=str(basin))])
    paths = write_selection_result(tmp_path, selection, selection_id="v1")
    dem = tmp_path / "dem.tif"
    if dem_crs == "broken":
        dem.write_text("not a raster", encoding="utf-8")
    elif dem_crs is not None:
        write_geotiff(dem, np.ones((2, 2)), crs=dem_crs or None)
    flow = {} if dem_crs is None else {"dem_path": str(dem)}
    manifest = {"output_root": str(tmp_path), "outputs": {key: path.name for key, path in paths.items()}, "flow_products": flow}  # fmt: skip
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    drawn: dict = {}
    monkeypatch.setattr(
        figures, "_write_map_png", lambda destination, **layers: drawn.update(layers)
    )

    render_site_selection_map(tmp_path / "manifest.json")

    # The map is drawn in the CRS of its DEM, else in the project CRS of the layers.
    project = Transformer.from_crs(L93, map_crs, always_xy=True).transform
    (outlet,) = drawn["selected_outlets"]
    assert outlet["geometry"]["coordinates"] == pytest.approx(project(X93, Y93), abs=1e-6)
    (contour,) = drawn["selected_basins"]
    assert shape(contour["geometry"]).centroid.coords[0] == pytest.approx(project(X93 + 50.0, Y93 + 50.0), abs=1e-2)  # fmt: skip


def test_the_display_bounds_can_keep_the_requested_regional_dem_extent():
    dem_extent, artifacts = (0.0, 0.0, 100.0, 100.0), (45.0, 45.0, 55.0, 55.0)

    assert _choose_display_bounds(dem_extent, artifacts) != dem_extent
    assert _choose_display_bounds(dem_extent, artifacts, prefer_dem_extent=True) == dem_extent
    manifest = {
        "dem": {"request_extent": "territory", "map_background_extent": "territory"},
        "flow_products": {"dem_path": "regional_dem.tif"},
    }
    assert _prefer_dem_extent_from_manifest(manifest) is True


def test_the_station_influence_block_lists_each_influenced_station(tmp_path):
    map_path = tmp_path / "map.png"
    map_path.write_bytes(b"fake")
    evidence = {
        "source_feature_id": "J123456701", "station_influence_status": "general_influence",
        "station_influence_flags": ["general_influence"], "matched_keywords": ["retenue"],
    }  # fmt: skip
    component = {
        "site_id": "site_001", "criterion_id": "station_influence", "criterion_family": "observations",
        "criterion_status": "warning", "raw_value": "general_influence", "evidence_json": evidence,
        "reason": "station has general hydrologic influence metadata",
    }  # fmt: skip
    manifest = dict.fromkeys(("counts", "territory", "criteria", "dem", "flow_products", "outputs"), {})  # fmt: skip
    strategy = {"principle": "observation_led", "candidate_mode": "station_outlets"}
    manifest |= {"selection_id": "station_influence_report", "strategy": strategy}

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
