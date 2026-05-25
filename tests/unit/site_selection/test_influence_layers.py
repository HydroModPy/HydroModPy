from __future__ import annotations

import json

import pytest

from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import (
    CriteriaConfig,
    InfluenceCriteriaConfig,
    InfluenceLayerConfig,
    SpatialSelectionConfig,
)
from hydromodpy.spatial.site_selection.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.influence import (
    annotate_catchments_with_influence_layers,
    write_influence_evidence_geojson,
)
from hydromodpy.spatial.site_selection.selection import select_delineated_catchments


@pytest.mark.fast
def test_influence_layer_sets_rejection_flag_from_basin_intersection(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point, Polygon

    basin_path = tmp_path / "basin.gpkg"
    influence_path = tmp_path / "dams.gpkg"
    gpd.GeoDataFrame(
        {"name": ["basin"]},
        geometry=[
            Polygon(
                [
                    (0.0, 0.0),
                    (100.0, 0.0),
                    (100.0, 100.0),
                    (0.0, 100.0),
                    (0.0, 0.0),
                ]
            )
        ],
        crs="EPSG:2154",
    ).to_file(basin_path, layer="basin", driver="GPKG")
    gpd.GeoDataFrame(
        {
            "id": ["DAM001"],
            "label": ["Demo dam"],
            "severity": ["major"],
        },
        geometry=[Point(40.0, 40.0)],
        crs="EPSG:2154",
    ).to_file(influence_path, layer="dams", driver="GPKG")
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 10.0, 10.0, "EPSG:2154", "test"),
        watershed_shp=str(basin_path),
        area_km2=1.0,
    )
    influence_config = InfluenceCriteriaConfig(
        mode="hard_reject",
        reject_major_dam_upstream=True,
        layers=[
            InfluenceLayerConfig(
                name="Dams",
                path=influence_path,
                influence_type="major_dam_upstream",
                id_field="id",
                label_field="label",
                severity_field="severity",
                major_values=["major"],
            )
        ],
    )

    annotated, evidence = annotate_catchments_with_influence_layers(
        [catchment],
        config=influence_config,
    )

    assert len(evidence) == 1
    assert evidence[0].feature_id == "DAM001"
    assert evidence[0].major is True
    assert annotated[0].outlet.attributes["major_dam_upstream"] is True
    assert annotated[0].outlet.attributes["upstream_dam_count"] == 1

    result = select_delineated_catchments(
        annotated,
        criteria=CriteriaConfig(influence=influence_config),
        spatial_selection=SpatialSelectionConfig(),
        selection_principle="observation_led",
    )
    assert result.selected == []
    assert result.rejected[0].site_id == "site_001"
    assert any(component.criterion_id == "influence" and component.blocking for component in result.criteria_components)


@pytest.mark.fast
def test_influence_evidence_geojson_export(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point, Polygon

    basin_path = tmp_path / "basin.gpkg"
    influence_path = tmp_path / "withdrawals.gpkg"
    gpd.GeoDataFrame(
        {"name": ["basin"]},
        geometry=[
            Polygon(
                [
                    (0.0, 0.0),
                    (100.0, 0.0),
                    (100.0, 100.0),
                    (0.0, 100.0),
                    (0.0, 0.0),
                ]
            )
        ],
        crs="EPSG:2154",
    ).to_file(basin_path, layer="basin", driver="GPKG")
    gpd.GeoDataFrame(
        {"id": ["W001"]},
        geometry=[Point(20.0, 20.0)],
        crs="EPSG:2154",
    ).to_file(influence_path, layer="withdrawals", driver="GPKG")
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", 10.0, 10.0, "EPSG:2154", "test"),
        watershed_shp=str(basin_path),
        area_km2=1.0,
    )

    _annotated, evidence = annotate_catchments_with_influence_layers(
        [catchment],
        config=InfluenceCriteriaConfig(
            layers=[
                InfluenceLayerConfig(
                    name="Withdrawals",
                    path=influence_path,
                    influence_type="major_withdrawal_upstream",
                    id_field="id",
                )
            ]
        ),
    )
    output = write_influence_evidence_geojson(tmp_path / "influence.geojson", evidence)

    assert output is not None
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["hydromodpy_geometry_role"] == "influence_features"
    assert payload["features"][0]["properties"]["influence_type"] == "major_withdrawal_upstream"
