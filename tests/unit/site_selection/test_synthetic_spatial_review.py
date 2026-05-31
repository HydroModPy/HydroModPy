from __future__ import annotations

import json

import pytest

from hydromodpy.reporting.site_selection.figures import (
    _choose_display_bounds,
    _prefer_dem_extent_from_manifest,
)
from hydromodpy.reporting.site_selection.html import render_site_selection_html_report
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.evaluation.selection import (
    SelectionDecision,
    SelectionResult,
)
from hydromodpy.spatial.site_selection.hydrology.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.outputs.artifacts import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.outputs.writer import (
    write_observation_points_geojson,
    write_selection_result,
)
from tests.unit.site_selection._geojson import write_polygon_geojson


@pytest.mark.fast
def test_synthetic_spatial_review_contains_basins_observations_map_and_html(tmp_path):
    pytest.importorskip("geopandas")

    selected_basin = tmp_path / "selected_basin.geojson"
    rejected_basin = tmp_path / "rejected_basin.geojson"
    write_polygon_geojson(
        selected_basin,
        coordinates=[
            [0.0, 0.0],
            [6.0, 0.0],
            [6.0, 4.0],
            [0.0, 4.0],
            [0.0, 0.0],
        ],
    )
    write_polygon_geojson(
        rejected_basin,
        coordinates=[
            [8.0, 0.0],
            [13.0, 0.0],
            [13.0, 4.0],
            [8.0, 4.0],
            [8.0, 0.0],
        ],
    )
    selected = DelineatedCatchment(
        site_id="site_selected",
        outlet=CandidateOutlet("cand_selected", 3.0, 1.0, "EPSG:2154", "synthetic"),
        watershed_shp=str(selected_basin),
        area_km2=24.0,
    )
    rejected = DelineatedCatchment(
        site_id="site_rejected",
        outlet=CandidateOutlet("cand_rejected", 10.0, 1.0, "EPSG:2154", "synthetic"),
        watershed_shp=str(rejected_basin),
        area_km2=20.0,
    )
    selection = SelectionResult(
        selected=[selected],
        rejected=[rejected],
        decisions=[
            SelectionDecision(
                site_id="site_selected",
                selection_principle="criteria_crossing",
                selected=True,
                decision_stage="selection",
                decision_reason="selected",
            ),
            SelectionDecision(
                site_id="site_rejected",
                selection_principle="criteria_crossing",
                selected=False,
                decision_stage="criteria",
                decision_reason="synthetic rejection",
                blocking_flags=["synthetic"],
            ),
        ],
        criteria_components=[],
    )
    cfg = SiteSelectionConfig.model_validate(
        {
            "selection_id": "synthetic_spatial_review",
            "output_root": tmp_path / "out",
            "strategy": {
                "principle": "criteria_crossing",
                "profile": "area_only",
                "primary_axes": ["area"],
                "observation_role": "report_only",
                "geology_role": "report_only",
            },
            "territory": {
                "mode": "bbox",
                "bbox": [0.0, 0.0, 13.0, 4.0],
            },
            "criteria": {
                "area": {
                    "mode": "hard_reject",
                    "hard_min_area_km2": 10.0,
                    "hard_max_area_km2": 30.0,
                }
            },
            "output": {"write_report_html": True},
        }
    )

    output_paths = write_selection_result(
        cfg.output_root,
        selection,
        selection_id=cfg.selection_id,
        region_id="synthetic",
    )
    output_paths["observation_points_geojson"] = write_observation_points_geojson(
        cfg.output_root / "observation_points.geojson",
        [
            _evidence("site_selected", "flow_station", "J000000001", 2.5, 1.5),
            _evidence("site_selected", "piezometer", "02478X0156", 4.5, 2.5),
        ],
    )
    output_paths.update(
        write_manifest_and_optional_report(
            config=cfg,
            selection=selection,
            output_paths=output_paths,
            action="synthetic_spatial_review",
            report_renderer=render_site_selection_html_report,
        )
    )

    selected_basins = json.loads(
        output_paths["selected_basins_geojson"].read_text(encoding="utf-8")
    )
    observations = json.loads(
        output_paths["observation_points_geojson"].read_text(encoding="utf-8")
    )
    html = output_paths["site_selection_report_html"].read_text(encoding="utf-8")

    assert selected_basins["features"][0]["geometry"]["type"] == "Polygon"
    assert selected_basins["hydromodpy_skipped_basins"] == []
    assert {feature["properties"]["observation_type"] for feature in observations["features"]} == {
        "flow_station",
        "piezometer",
    }
    assert output_paths["site_selection_map_png"].stat().st_size > 20_000
    assert "site_selection_map.png" in html
    assert "Carte de controle" in html
    assert "fixture ou synthetiques" in html


@pytest.mark.fast
def test_display_bounds_can_honor_requested_regional_dem_extent():
    dem_extent = (0.0, 0.0, 100.0, 100.0)
    artifact_bounds = (45.0, 45.0, 55.0, 55.0)

    assert _choose_display_bounds(dem_extent, artifact_bounds) != dem_extent
    assert _choose_display_bounds(dem_extent, artifact_bounds, prefer_dem_extent=True) == dem_extent


@pytest.mark.fast
def test_manifest_prefers_dem_extent_for_territory_background():
    manifest = {
        "dem": {"request_extent": "territory", "map_background_extent": "territory"},
        "flow_products": {"dem_path": "regional_dem.tif"},
    }

    assert _prefer_dem_extent_from_manifest(manifest) is True


def _evidence(
    site_id: str,
    observation_type: str,
    feature_id: str,
    x: float,
    y: float,
) -> ObservationEvidence:
    return ObservationEvidence(
        site_id=site_id,
        observation_type=observation_type,
        source_dataset="synthetic",
        feature_id=feature_id,
        feature_label=feature_id,
        record_year_count=5.0,
        evidence_json={
            "provider_location": {
                "x": x,
                "y": y,
                "crs": "EPSG:2154",
            }
        },
    )
