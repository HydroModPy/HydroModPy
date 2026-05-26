from __future__ import annotations

import json

import pytest

from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import (
    CriteriaConfig,
    GeologyCriteriaConfig,
    GeologyLayerConfig,
    ObservationsCriteriaConfig,
    PiezometerLayerConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.context_evidence import (
    annotate_catchments_with_geology_layers,
    annotate_catchments_with_piezometer_layers,
    write_geology_evidence_geojson,
)
from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.selection import select_delineated_catchments
from hydromodpy.workflow.site_selection import select_delineated_catchments_from_csv


@pytest.mark.fast
def test_geology_layer_sets_dominant_geology_from_basin_intersection(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    basin_path = tmp_path / "basin.gpkg"
    geology_path = tmp_path / "geology.gpkg"
    _write_basin(gpd, basin_path)
    gpd.GeoDataFrame(
        {
            "id": ["G001", "G002"],
            "label": ["Schist unit", "Granite unit"],
            "class": ["schist", "granite"],
        },
        geometry=[
            Polygon([(0.0, 0.0), (60.0, 0.0), (60.0, 100.0), (0.0, 100.0), (0.0, 0.0)]),
            Polygon([(60.0, 0.0), (100.0, 0.0), (100.0, 100.0), (60.0, 100.0), (60.0, 0.0)]),
        ],
        crs="EPSG:2154",
    ).to_file(geology_path, layer="geology", driver="GPKG")
    catchment = _catchment(basin_path)
    geology_config = GeologyCriteriaConfig(
        mode="stratify",
        layers=[
            GeologyLayerConfig(
                name="BRGM demo",
                path=geology_path,
                class_field="class",
                id_field="id",
                label_field="label",
            )
        ],
    )

    annotated, evidence = annotate_catchments_with_geology_layers(
        [catchment],
        config=geology_config,
    )

    attributes = annotated[0].outlet.attributes
    assert attributes["dominant_geology"] == "schist"
    assert attributes["geology_diversity_count"] == 2
    assert len(evidence) == 2
    assert {item.geology_class for item in evidence} == {"granite", "schist"}

    result = select_delineated_catchments(
        annotated,
        criteria=CriteriaConfig(geology=geology_config),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )
    geology_component = next(
        component
        for component in result.criteria_components
        if component.criterion_id == "geology"
    )
    assert geology_component.raw_value == "schist"
    assert geology_component.criterion_status == "stratified"

    output = write_geology_evidence_geojson(tmp_path / "geology_basins.geojson", evidence)
    assert output is not None
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["hydromodpy_geometry_role"] == "geology_basins"
    assert len(payload["features"]) == 2


@pytest.mark.fast
def test_piezometer_layer_sets_observation_evidence_and_distance_attributes(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    basin_path = tmp_path / "basin.gpkg"
    piezometer_path = tmp_path / "piezometers.gpkg"
    _write_basin(gpd, basin_path)
    gpd.GeoDataFrame(
        {
            "id": ["PZ001", "PZ_FAR"],
            "label": ["Close piezometer", "Far piezometer"],
            "years": [4.5, 2.0],
            "quality": ["good", "partial"],
        },
        geometry=[Point(10.0, 10.0), Point(5000.0, 5000.0)],
        crs="EPSG:2154",
    ).to_file(piezometer_path, layer="piezometers", driver="GPKG")
    catchment = _catchment(basin_path)
    observations_config = ObservationsCriteriaConfig(
        piezometer_mode="hard_reject",
        piezometer_max_distance_km=1.0,
        piezometer_layers=[
            PiezometerLayerConfig(
                name="BSS demo",
                path=piezometer_path,
                id_field="id",
                label_field="label",
                record_years_field="years",
                quality_field="quality",
            )
        ],
    )

    annotated, evidence = annotate_catchments_with_piezometer_layers(
        [catchment],
        config=observations_config,
    )

    attributes = annotated[0].outlet.attributes
    assert attributes["piezometer_count"] == 1
    assert attributes["piezometers_in_basin"] == 1
    assert attributes["piezometer_inside_basin"] is True
    assert attributes["nearest_piezometer_distance_km"] == pytest.approx(0.014142, rel=1e-3)
    assert evidence[0].feature_id == "PZ001"
    assert evidence[0].record_year_count == pytest.approx(4.5)
    assert evidence[0].evidence_json["provider_location"]["crs"] == "EPSG:2154"

    result = select_delineated_catchments(
        annotated,
        criteria=CriteriaConfig(observations=observations_config),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="criteria_crossing",
    )
    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    piezometer_component = next(
        component
        for component in result.criteria_components
        if component.criterion_id == "piezometer"
    )
    assert piezometer_component.criterion_status == "passed"


@pytest.mark.fast
def test_workflow_writes_geology_and_piezometer_outputs_from_configured_layers(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point, Polygon

    basin_path = tmp_path / "basin.gpkg"
    geology_path = tmp_path / "geology.gpkg"
    piezometer_path = tmp_path / "piezometers.gpkg"
    _write_basin(gpd, basin_path)
    gpd.GeoDataFrame(
        {"id": ["G001"], "class": ["schist"]},
        geometry=[Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)])],
        crs="EPSG:2154",
    ).to_file(geology_path, layer="geology", driver="GPKG")
    gpd.GeoDataFrame(
        {"id": ["PZ001"], "label": ["Close piezometer"]},
        geometry=[Point(10.0, 10.0)],
        crs="EPSG:2154",
    ).to_file(piezometer_path, layer="piezometers", driver="GPKG")
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "site_id,x,y,outlet_crs,area_km2,watershed_shp\n"
        "site_001,0,0,EPSG:2154,0.01,basin.gpkg\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "context_layers_demo"',
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
                'mode = "bbox"',
                "bbox = [0.0, 0.0, 100.0, 100.0]",
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 0.001",
                "hard_max_area_km2 = 1.0",
                "",
                "[[site_selection.criteria.geology.layers]]",
                'name = "BRGM demo"',
                'path = "geology.gpkg"',
                'class_field = "class"',
                'id_field = "id"',
                "",
                "[[site_selection.criteria.observations.piezometer_layers]]",
                'name = "BSS demo"',
                'path = "piezometers.gpkg"',
                'id_field = "id"',
                'label_field = "label"',
                "",
                "[site_selection.output]",
                "write_geopackage = true",
            ]
        ),
        encoding="utf-8",
    )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
    )

    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    assert paths["geology_evidence_jsonl"].is_file()
    assert paths["geology_basins_geojson"].is_file()
    assert paths["piezometer_evidence_jsonl"].is_file()
    assert paths["observation_evidence_jsonl"].is_file()
    assert paths["site_selection_evidence_jsonl"].is_file()
    assert paths["observation_points_geojson"].is_file()
    assert paths["site_selection_gpkg"].is_file()
    layers = set(gpd.list_layers(paths["site_selection_gpkg"])["name"])
    assert "geology_basins" in layers
    assert "observation_points" in layers


def _write_basin(gpd, basin_path):
    from shapely.geometry import Polygon

    gpd.GeoDataFrame(
        {"name": ["basin"]},
        geometry=[
            Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)])
        ],
        crs="EPSG:2154",
    ).to_file(basin_path, layer="basin", driver="GPKG")


def _catchment(basin_path):
    return DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 0.0, 0.0, "EPSG:2154", "test"),
        watershed_shp=str(basin_path),
        area_km2=0.01,
    )
