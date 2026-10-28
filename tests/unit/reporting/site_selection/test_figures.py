"""The control map of a site selection shows its basins and observations."""

from __future__ import annotations

import json

import pytest
from shapely.geometry import box

from hydromodpy.reporting.site_selection.figures import (
    _choose_display_bounds,
    _prefer_dem_extent_from_manifest,
)
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionDecision
from hydromodpy.spatial.site_selection.outputs.artifacts import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.outputs.geojson import write_observation_points_geojson
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.site_selection_cases import (
    make_catchment,
    make_selection,
    selection_section,
    write_vector_layer,
)

pytestmark = pytest.mark.fast


def _evidence(observation_type: str, feature_id: str, x: float, y: float):
    return ObservationEvidence(
        site_id="site_selected",
        observation_type=observation_type,
        source_dataset="synthetic",
        feature_id=feature_id,
        record_year_count=5.0,
        evidence_json={"provider_location": {"x": x, "y": y, "crs": "EPSG:2154"}},
    )


def _site(tmp_path, name: str, x0: float, x1: float, area_km2: float):
    basin = write_vector_layer(tmp_path / f"{name}.geojson", [box(x0, 0.0, x1, 4.0)])
    return make_catchment(
        name,
        x=(x0 + x1) / 2,
        y=1.0,
        area_km2=area_km2,
        source="synthetic",
        watershed_shp=str(basin),
    )


def test_a_synthetic_review_shows_basins_observations_and_the_control_map(tmp_path):
    rejection = SelectionDecision(
        site_id="site_rejected", selection_principle="criteria_crossing", selected=False,
        decision_stage="criteria", decision_reason="synthetic rejection", blocking_flags=["x"],
    )  # fmt: skip
    selection = make_selection(
        [_site(tmp_path, "site_selected", 0.0, 6.0, 24.0)],
        [_site(tmp_path, "site_rejected", 8.0, 13.0, 20.0)],
        decisions=[rejection],
    )
    area = {"mode": "hard_reject", "hard_min_area_km2": 10.0, "hard_max_area_km2": 30.0}
    section = selection_section(
        output_root=tmp_path / "out", territory={"mode": "bbox", "bbox": [0.0, 0.0, 13.0, 4.0]},
        criteria={"area": area}, output={"write_report_html": True},
    )  # fmt: skip
    config = SiteSelectionConfig.model_validate(section)

    paths = write_selection_result(config.output_root, selection, selection_id="review")
    paths["observation_points_geojson"] = write_observation_points_geojson(
        tmp_path / "observation_points.geojson",
        [
            _evidence("flow_station", "J000000001", 2.5, 1.5),
            _evidence("piezometer", "PZ1", 4.5, 2.5),
        ],
    )
    paths |= write_manifest_and_optional_report(
        config=config, selection=selection, output_paths=paths, action="synthetic_spatial_review",
        report_renderer=render_site_selection_html_report,
    )  # fmt: skip

    basins = json.loads(paths["selected_basins_geojson"].read_text(encoding="utf-8"))
    assert (basins["features"][0]["geometry"]["type"], basins["hydromodpy_skipped_basins"]) == ("Polygon", [])  # fmt: skip
    observations = json.loads(paths["observation_points_geojson"].read_text(encoding="utf-8"))
    assert {item["properties"]["observation_type"] for item in observations["features"]} == {
        "flow_station", "piezometer",
    }  # fmt: skip
    assert paths["site_selection_map_png"].stat().st_size > 20_000
    html = paths["site_selection_report_html"].read_text(encoding="utf-8")
    for text in ("site_selection_map.png", "Control map", "fixture or synthetic"):
        assert text in html
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    observations_path = str(tmp_path / "observation_points.geojson")
    assert manifest["outputs"]["observation_points_geojson"] == observations_path


def test_the_display_bounds_can_keep_the_requested_regional_dem_extent():
    dem_extent, artifacts = (0.0, 0.0, 100.0, 100.0), (45.0, 45.0, 55.0, 55.0)

    assert _choose_display_bounds(dem_extent, artifacts) != dem_extent
    assert _choose_display_bounds(dem_extent, artifacts, prefer_dem_extent=True) == dem_extent
    manifest = {
        "dem": {"request_extent": "territory", "map_background_extent": "territory"},
        "flow_products": {"dem_path": "regional_dem.tif"},
    }
    assert _prefer_dem_extent_from_manifest(manifest) is True
