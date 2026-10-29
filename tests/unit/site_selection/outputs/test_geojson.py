"""Every GeoJSON of the site selection opens in the CRS it was written in.

A file written in Lambert-93 with only the ``hydromodpy_coordinate_crs`` key
opened in WGS 84 in geopandas, QGIS and ``hmp sites import``, with latitudes in
the millions. Each writer now names its CRS in the ``crs`` member that GDAL reads.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from hydromodpy.core.io.crs import geojson_crs_member
from hydromodpy.data.sites.importers import rows_from_layer
from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.outputs import geospatial
from hydromodpy.spatial.site_selection.outputs.candidate_files import (
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.outputs.evidence_layers import write_evidence_layer
from hydromodpy.spatial.site_selection.outputs.geojson import write_observation_points_geojson
from hydromodpy.spatial.site_selection.outputs.geospatial import observation_points_gdf
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.site_selection_cases import (
    L93,
    X93,
    Y93,
    make_catchment,
    make_selection,
    site_flow_products,
    write_accumulation_raster,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

BASIN = box(X93 - 500.0, Y93 - 400.0, X93 + 500.0, Y93 + 400.0)
NETWORK = [[1.0, 1.0, 1.0], [1.0, 50.0, 60.0], [1.0, 1.0, 70.0]]


def _selection(tmp_path: Path, key: str) -> Path:
    basin = write_vector_layer(tmp_path / "basin.gpkg", [BASIN], name=["basin"])
    catchment = make_catchment(x=X93, y=Y93, area_km2=0.8, watershed_shp=str(basin))
    return write_selection_result(tmp_path / "out", make_selection([catchment]), selection_id="v1")[
        key
    ]


def _observations(tmp_path: Path) -> Path:
    location = {"provider_location": {"x": X93, "y": Y93, "crs": L93}}
    evidence = ObservationEvidence("site_001", "flow_station", "hubeau", "J001401001", evidence_json=location)  # fmt: skip
    return write_observation_points_geojson(tmp_path / "observation_points.geojson", [evidence])


def _candidates(tmp_path: Path) -> Path:
    outlet = CandidateOutlet("cand_001", X93, Y93, L93, "test")
    return write_candidate_outlets_geojson(tmp_path / "candidates.geojson", [outlet])


def _network(tmp_path: Path, accumulation=NETWORK, **kwargs) -> Path:
    acc = write_accumulation_raster(tmp_path / "acc.tif", np.array(accumulation))
    return write_generated_network_geojson(
        tmp_path / "network.geojson",
        flow_products=site_flow_products(acc),
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
        **kwargs,
    )


def _evidence(tmp_path: Path, role: str) -> Path:
    common = dict(site_id="site_001", crs=L93)
    evidence = (
        GeologyEvidence(source_layer="geology", geology_class="granite", area_fraction=1.0,
                        area_km2=0.8, feature_count=1, geometry=BASIN, **common)
        if role == "geology_basins"
        else InfluenceEvidence(influence_type="dam", source_layer="dams", geometry=Point(X93, Y93), **common)
    )  # fmt: skip
    return write_evidence_layer(tmp_path / f"{role}.geojson", [evidence], role=role, fmt="geojson")


WRITERS: dict[str, Callable[[Path], Path]] = {
    "selected-outlets": lambda tmp_path: _selection(tmp_path, "selected_outlets_geojson"),
    "selected-basins": lambda tmp_path: _selection(tmp_path, "selected_basins_geojson"),
    "observation-points": _observations,
    "candidate-outlets": _candidates,
    "generated-network": _network,
    "geology-evidence": lambda tmp_path: _evidence(tmp_path, "geology_basins"),
    "influence-evidence": lambda tmp_path: _evidence(tmp_path, "influence_features"),
}


@pytest.mark.parametrize("writer", WRITERS)
def test_a_site_selection_geojson_opens_in_its_crs(tmp_path: Path, writer: str):
    path = WRITERS[writer](tmp_path)

    frame = gpd.read_file(path)

    assert frame.crs == L93
    assert json.loads(path.read_text())["hydromodpy_coordinate_crs"] == L93


def test_hmp_sites_import_reads_the_selected_outlets_in_lambert_93(tmp_path: Path):
    path = _selection(tmp_path, "selected_outlets_geojson")

    (row,) = rows_from_layer(path, name_field="site_id").rows

    assert (row.x_outlet, row.y_outlet) == (X93, Y93)
    assert row.crs == L93


@pytest.mark.parametrize("label", ["", "mixed", 'LOCAL_CS["engineering"]'])
def test_a_crs_without_an_epsg_code_writes_no_crs_member(label: str):
    assert geojson_crs_member(label) == {}


def test_the_generated_network_is_written_as_stream_segments(tmp_path):
    payload = json.loads(_network(tmp_path).read_text(encoding="utf-8"))

    assert payload["hydromodpy_geometry_role"] == "generated_dem_network"
    assert payload["hydromodpy_coordinate_crs"] == "EPSG:2154"
    assert any(feature["geometry"]["type"] == "LineString" for feature in payload["features"])


def test_the_generated_network_stays_inside_the_search_geometry(tmp_path):
    accumulation = [[90.0, 1.0, 1.0], [90.0, 1.0, 80.0], [90.0, 1.0, 80.0]]

    path = _network(tmp_path, accumulation, search_geometry=box(20.0, 0.0, 30.0, 20.0))

    xs = [
        point[0]
        for feature in json.loads(path.read_text(encoding="utf-8"))["features"]
        for point in (
            [feature["geometry"]["coordinates"]]
            if feature["geometry"]["type"] == "Point"
            else feature["geometry"]["coordinates"]
        )
    ]
    assert xs
    assert min(xs) >= 20.0


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
    path = write_observation_points_geojson(tmp_path / "obs.geojson", ROWS)
    collection = json.loads(path.read_text())

    assert list(frame["site_id"]) == ["a", "b"] == [f["properties"]["site_id"] for f in collection["features"]]  # fmt: skip
    assert frame.crs == L93
    skipped = collection["hydromodpy_skipped_observations"]
    assert [item["site_id"] for item in skipped] == list("cdef")
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
