from __future__ import annotations

import csv
import json

import pytest

from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import AreaCriteriaConfig, CriteriaConfig
from hydromodpy.spatial.site_selection.criteria import evaluate_area_criterion
from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.exports import (
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
    write_observation_points_geojson,
    write_selection_result,
)
from hydromodpy.spatial.site_selection.selection import SelectionDecision, SelectionResult
from hydromodpy.spatial.site_selection.types import ObservationEvidence


@pytest.mark.fast
def test_site_record_from_catchment_matches_regional_lab_core_fields():
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 350000.0, 6810000.0, "EPSG:2154", "test"),
        area_km2=101.5,
    )

    row = site_record_from_catchment(
        catchment,
        selection_id="selection_v1",
        region_id="Bretagne",
    )

    assert row["site_id"] == "site_001"
    assert row["source_selection_id"] == "selection_v1"
    assert row["region_id"] == "Bretagne"
    assert row["x_outlet"] == pytest.approx(350000.0)
    assert row["area_km2"] == pytest.approx(101.5)
    assert row["enabled"] is True


@pytest.mark.fast
def test_write_selection_result_outputs_core_files(tmp_path):
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 350000.0, 6810000.0, "EPSG:2154", "test"),
        area_km2=101.5,
    )
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=101.5,
        config=AreaCriteriaConfig(mode="report_only"),
        selection_principle="criteria_crossing",
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[
            SelectionDecision(
                site_id="site_001",
                selection_principle="criteria_crossing",
                selected=True,
                decision_stage="selection",
                decision_reason="selected",
            )
        ],
        criteria_components=[component],
    )

    paths = write_selection_result(
        tmp_path,
        result,
        selection_id="selection_v1",
        region_id="Bretagne",
    )

    assert paths["selected_sites_csv"].is_file()
    assert paths["regional_lab_sites_csv"].is_file()
    assert paths["selected_outlets_geojson"].is_file()
    assert paths["selected_basins_geojson"].is_file()
    assert paths["criteria_components_jsonl"].is_file()

    with paths["regional_lab_sites_csv"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["site_id"] == "site_001"
    assert rows[0]["source_selection_id"] == "selection_v1"

    first_component = json.loads(paths["criteria_components_jsonl"].read_text().splitlines()[0])
    assert first_component["criterion_id"] == "area"

    geojson = json.loads(paths["selected_outlets_geojson"].read_text(encoding="utf-8"))
    assert geojson["features"][0]["geometry"]["type"] == "Point"
    assert geojson["features"][0]["properties"]["outlet_crs"] == "EPSG:2154"


@pytest.mark.fast
def test_write_selection_result_exports_snapped_outlet_geometry(tmp_path):
    snap_path = tmp_path / "outlet_snap.geojson"
    snap_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [350030.0, 6810040.0],
                        },
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 350000.0, 6810000.0, "EPSG:2154", "test"),
        outlet_snap_shp=str(snap_path),
        area_km2=101.5,
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[],
        criteria_components=[],
    )

    paths = write_selection_result(tmp_path / "out", result, selection_id="selection_v1")

    geojson = json.loads(paths["selected_outlets_geojson"].read_text(encoding="utf-8"))
    feature = geojson["features"][0]
    assert feature["geometry"]["coordinates"] == [350030.0, 6810040.0]
    assert feature["properties"]["outlet_geometry_source"] == "snapped"
    assert feature["properties"]["outlet_original_x"] == pytest.approx(350000.0)
    assert feature["properties"]["x_outlet_snapped"] == pytest.approx(350030.0)
    assert feature["properties"]["outlet_snap_distance_m"] == pytest.approx(50.0)

    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        selected_rows = list(csv.DictReader(handle))
    assert selected_rows[0]["x_outlet_snapped"] == "350030.0"
    assert float(selected_rows[0]["outlet_snap_distance_m"]) == pytest.approx(50.0)

    with paths["regional_lab_sites_csv"].open(newline="", encoding="utf-8") as handle:
        regional_header = next(csv.reader(handle))
    assert "x_outlet_snapped" not in regional_header


@pytest.mark.fast
def test_write_selection_result_honors_tabular_output_switches(tmp_path):
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 350000.0, 6810000.0, "EPSG:2154", "test"),
        area_km2=101.5,
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[
            SelectionDecision(
                site_id="site_001",
                selection_principle="criteria_crossing",
                selected=True,
                decision_stage="selection",
                decision_reason="selected",
            )
        ],
        criteria_components=[],
    )

    paths = write_selection_result(
        tmp_path,
        result,
        selection_id="selection_v1",
        write_selected=False,
        write_rejected=False,
        write_regional_lab_csv_output=False,
    )

    assert "selected_sites_csv" not in paths
    assert "rejected_sites_csv" not in paths
    assert "regional_lab_sites_csv" not in paths
    assert paths["selected_outlets_geojson"].is_file()
    assert paths["selected_basins_geojson"].is_file()
    assert paths["selection_decisions_jsonl"].is_file()
    assert paths["criteria_components_jsonl"].is_file()


@pytest.mark.fast
def test_write_selection_result_exports_available_basin_contours(tmp_path):
    pytest.importorskip("geopandas")
    basin_path = tmp_path / "basin.geojson"
    basin_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [0.0, 0.0],
                                    [10.0, 0.0],
                                    [10.0, 8.0],
                                    [0.0, 8.0],
                                    [0.0, 0.0],
                                ]
                            ],
                        },
                        "properties": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 5.0, 4.0, "EPSG:2154", "test"),
        watershed_shp=str(basin_path),
        area_km2=0.00008,
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[],
        criteria_components=[],
    )

    paths = write_selection_result(tmp_path / "out", result, selection_id="selection_v1")

    basin_geojson = json.loads(paths["selected_basins_geojson"].read_text(encoding="utf-8"))
    assert basin_geojson["features"][0]["geometry"]["type"] == "Polygon"
    assert basin_geojson["features"][0]["properties"]["site_id"] == "site_001"
    assert basin_geojson["hydromodpy_skipped_basins"] == []


@pytest.mark.fast
def test_write_selection_result_exports_production_vector_layers(tmp_path):
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("pyarrow")
    from shapely.geometry import Polygon

    basin_path = tmp_path / "basin.gpkg"
    gpd.GeoDataFrame(
        {"name": ["basin"]},
        geometry=[
            Polygon(
                [
                    (0.0, 0.0),
                    (10.0, 0.0),
                    (10.0, 8.0),
                    (0.0, 8.0),
                    (0.0, 0.0),
                ]
            )
        ],
        crs="EPSG:2154",
    ).to_file(basin_path, layer="basin", driver="GPKG")
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 5.0, 4.0, "EPSG:2154", "test"),
        watershed_shp=str(basin_path),
        area_km2=0.00008,
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[],
        criteria_components=[],
    )

    paths = write_selection_result(
        tmp_path / "out",
        result,
        selection_id="selection_v1",
        write_geopackage=True,
        write_geoparquet=True,
    )

    assert paths["site_selection_gpkg"].is_file()
    assert paths["selected_outlets_geoparquet"].is_file()
    assert paths["selected_basins_geoparquet"].is_file()
    selected_outlets = gpd.read_file(paths["site_selection_gpkg"], layer="selected_outlets")
    selected_basins = gpd.read_file(paths["site_selection_gpkg"], layer="selected_basins")
    assert selected_outlets.crs.to_string() == "EPSG:2154"
    assert selected_outlets.loc[0, "site_id"] == "site_001"
    assert selected_basins.loc[0, "site_id"] == "site_001"

    parquet_outlets = gpd.read_parquet(paths["selected_outlets_geoparquet"])
    parquet_basins = gpd.read_parquet(paths["selected_basins_geoparquet"])
    assert parquet_outlets.crs.to_string() == "EPSG:2154"
    assert parquet_basins.crs.to_string() == "EPSG:2154"


@pytest.mark.fast
def test_write_observation_points_geojson_uses_provider_locations(tmp_path):
    evidence = ObservationEvidence(
        site_id="site_001",
        observation_type="flow_station",
        source_dataset="hubeau",
        feature_id="J001401001",
        feature_label="Station demo",
        record_year_count=3.0,
        evidence_json={
            "provider_location": {
                "x": 350000.0,
                "y": 6810000.0,
                "crs": "EPSG:2154",
            }
        },
    )

    path = write_observation_points_geojson(tmp_path / "observation_points.geojson", [evidence])

    geojson = json.loads(path.read_text(encoding="utf-8"))
    assert geojson["features"][0]["geometry"]["type"] == "Point"
    assert geojson["features"][0]["properties"]["observation_type"] == "flow_station"
    assert geojson["features"][0]["properties"]["observation_crs"] == "EPSG:2154"


@pytest.mark.fast
def test_selected_sites_schema_matches_csv_header(tmp_path):
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 350000.0, 6810000.0, "EPSG:2154", "test"),
        area_km2=101.5,
    )
    result = SelectionResult(
        selected=[catchment],
        rejected=[],
        decisions=[],
        criteria_components=[],
    )

    paths = write_selection_result(
        tmp_path,
        result,
        selection_id="selection_v1",
        write_geojson=False,
    )

    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
    assert header == SELECTED_SITES_FIELDS
    assert list(SELECTED_SITES_SCHEMA) == SELECTED_SITES_FIELDS


@pytest.mark.fast
def test_criteria_config_rejects_duplicate_criterion_lists():
    with pytest.raises(ValueError, match="area_preference"):
        CriteriaConfig(
            hard_reject=["area_preference"],
            report_only=["area_preference"],
        )
