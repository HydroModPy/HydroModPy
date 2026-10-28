"""GeoPackage and GeoParquet layers of a selection and of its observation points."""

from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from hydromodpy.spatial.site_selection.outputs import geospatial
from hydromodpy.spatial.site_selection.outputs.geojson import write_observation_points_geojson
from hydromodpy.spatial.site_selection.outputs.geospatial import observation_points_gdf
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.site_selection_cases import (
    L93,
    make_catchment,
    make_selection,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

BOWTIE = Polygon([(0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0), (0.0, 0.0)])


@pytest.mark.parametrize("basin", [box(0.0, 0.0, 10.0, 8.0), BOWTIE], ids=["valid", "bowtie"])
def test_the_selection_layers_open_in_their_crs_with_valid_basins(tmp_path, basin):
    basin_path = write_vector_layer(tmp_path / "basin.gpkg", [basin])
    selected = make_catchment(
        "site_001", x=5.0, y=4.0, watershed_shp=str(basin_path),
        attributes={"reference_network_source": "bdtopage"},
    )  # fmt: skip
    rejected = make_catchment("site_002", x=50.0, y=4.0, watershed_shp=str(basin_path))
    result = make_selection([selected], [rejected])
    write = dict(selection_id="v1", write_geopackage=True, write_geoparquet=True)

    write_selection_result(tmp_path / "out", result, **write)
    paths = write_selection_result(tmp_path / "out", result, **write)

    layers = set(gpd.list_layers(paths["site_selection_gpkg"])["name"])
    assert layers == {"selected_outlets", "rejected_outlets", "selected_basins", "rejected_basins"}
    outlets = gpd.read_file(paths["site_selection_gpkg"], layer="selected_outlets")
    assert (outlets.crs, outlets.loc[0, "site_id"]) == (L93, "site_001")
    assert outlets.loc[0, "reference_network_source"] == "bdtopage"
    for key in ("selected_outlets", "rejected_outlets", "selected_basins", "rejected_basins"):
        frame = gpd.read_parquet(paths[f"{key}_geoparquet"])
        assert frame.crs == L93
        assert frame.geometry.is_valid.all()
    basins = gpd.read_file(paths["site_selection_gpkg"], layer="selected_basins")
    assert basins.geometry.iloc[0].is_valid
    assert basins.geometry.iloc[0].area == pytest.approx(80.0 if basin.is_valid else 50.0)
    assert json.loads(paths["selected_basins_geojson"].read_text())["features"]


ROWS = [
    {"site_id": "a", "feature_id": "1",
     "evidence_json": json.dumps({"provider_location": {"x": 1.0, "y": 2.0, "crs": L93}})},
    {"site_id": "b", "feature_id": "2", "evidence_json": {"provider_location": {"x": 3, "y": 4}}},
    {"site_id": "c", "feature_id": "3", "evidence_json": "{not json"},
    {"site_id": "d", "feature_id": "4", "evidence_json": [1, 2]},
    {"site_id": "e", "feature_id": "5", "evidence_json": {"provider_location": {"x": "east"}}},
    {"site_id": "f", "feature_id": "6", "evidence_json": {"provider_location": "here"}},
]  # fmt: skip


def test_observation_points_keep_only_rows_with_a_readable_location(tmp_path):
    frame = observation_points_gdf(ROWS)
    collection = json.loads(
        write_observation_points_geojson(tmp_path / "obs.geojson", ROWS).read_text()
    )

    assert list(frame["site_id"]) == ["a", "b"] == [f["properties"]["site_id"] for f in collection["features"]]  # fmt: skip
    assert frame.crs == L93
    assert [item["site_id"] for item in collection["hydromodpy_skipped_observations"]] == list(
        "cdef"
    )
    assert list(frame.geometry.x) == [1.0, 3.0]
    assert [f["properties"]["observation_crs"] for f in collection["features"]] == [L93, ""]
    assert geospatial.write_vector_layer(frame, tmp_path / "obs.gpkg", fmt="gpkg").is_file()
    parquet = geospatial.write_vector_layer(frame, tmp_path / "obs.parquet", fmt="geoparquet")
    assert gpd.read_parquet(parquet).crs == L93


def test_no_observation_point_writes_no_file(tmp_path):
    empty = observation_points_gdf(ROWS[2:])
    assert geospatial.write_vector_layer(empty, tmp_path / "obs.gpkg", fmt="gpkg") is None
    assert geospatial.write_vector_layer(empty, tmp_path / "obs.parquet", fmt="geoparquet") is None
    assert not list(tmp_path.iterdir())
