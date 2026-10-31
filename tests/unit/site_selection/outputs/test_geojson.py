"""Every GeoJSON of the site selection follows RFC 7946.

Its coordinates are WGS 84 longitudes and latitudes and it carries no ``crs``
member. ``hydromodpy_project_crs`` names the CRS the features came from. The
project coordinates stay in the GeoPackage and GeoParquet layers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from hydromodpy.core.exceptions import ExportError
from hydromodpy.data.sites.importers import rows_from_layer
from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.hydrology.worker import _write_outlet_roll_call
from hydromodpy.spatial.site_selection.outputs import geospatial
from hydromodpy.spatial.site_selection.outputs.candidate_files import (
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.outputs.evidence_layers import write_evidence_layer
from hydromodpy.spatial.site_selection.outputs.geojson import (
    write_observation_points_geojson,
    write_outlets_geojson,
)
from hydromodpy.spatial.site_selection.outputs.geospatial import observation_points_gdf
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.site_selection_cases import (
    L93,
    X93,
    Y93,
    make_catchment,
    make_selection,
    site_flow_products,
    to_wgs84,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

BASIN = box(X93 - 500.0, Y93 - 400.0, X93 + 500.0, Y93 + 400.0)
NETWORK = [[1.0, 1.0, 1.0], [1.0, 50.0, 60.0], [1.0, 1.0, 70.0]]


def _selection(tmp_path: Path, key: str) -> Path:
    basin = write_vector_layer(tmp_path / "basin.gpkg", [BASIN], name=["basin"])
    catchment = make_catchment(x=X93, y=Y93, area_km2=0.8, watershed_shp=str(basin))
    selection = make_selection([catchment])
    return write_selection_result(tmp_path / "out", selection, selection_id="v1", write_geopackage=True)[key]  # fmt: skip


def _observations(tmp_path: Path) -> Path:
    location = {"provider_location": {"x": X93, "y": Y93, "crs": L93}}
    evidence = ObservationEvidence("site_001", "flow_station", "hubeau", "J001401001", evidence_json=location)  # fmt: skip
    return write_observation_points_geojson(tmp_path / "observation_points.geojson", [evidence])


def _candidates(tmp_path: Path) -> Path:
    outlet = CandidateOutlet("cand_001", X93, Y93, L93, "test")
    return write_candidate_outlets_geojson(tmp_path / "candidates.geojson", [outlet])


def _network(tmp_path: Path, accumulation=NETWORK, crs: str | None = L93, **kwargs) -> Path:
    acc = write_geotiff(tmp_path / "acc.tif", np.array(accumulation), cell=10.0, crs=crs, nodata=-9999.0)  # fmt: skip
    return write_generated_network_geojson(
        tmp_path / "network.geojson",
        flow_products=site_flow_products(acc),
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
        **kwargs,
    )


def _evidence(tmp_path: Path, role: str, crs: str = L93) -> Path:
    common = dict(site_id="site_001", crs=crs)
    evidence = (
        GeologyEvidence(source_layer="geology", geology_class="granite", area_fraction=1.0,
                        area_km2=0.8, feature_count=1, geometry=BASIN, **common)
        if role == "geology_basins"
        else InfluenceEvidence(influence_type="dam", source_layer="dams", geometry=Point(X93, Y93), **common)
    )  # fmt: skip
    return write_evidence_layer(tmp_path / f"{role}.geojson", [evidence], role=role, fmt="geojson")


def _roll_call(tmp_path: Path) -> Path:
    (tmp_path / "outputs").mkdir()
    job = SimpleNamespace(resolve_output=lambda relative: tmp_path / relative)
    _write_outlet_roll_call(job, [make_catchment(x=X93, y=Y93)], crs=L93)
    return tmp_path / "outputs" / "outlets_snapped.geojson"


OUTLET_BOUNDS = (X93, Y93, X93, Y93)
WRITERS: dict[str, tuple[Callable[[Path], Path], tuple[float, ...]]] = {
    "selected-outlets": (lambda tmp_path: _selection(tmp_path, "selected_outlets_geojson"), OUTLET_BOUNDS),
    "selected-basins": (lambda tmp_path: _selection(tmp_path, "selected_basins_geojson"), BASIN.bounds),
    "observation-points": (_observations, OUTLET_BOUNDS),
    "candidate-outlets": (_candidates, OUTLET_BOUNDS),
    "generated-network": (_network, (5.0, 5.0, 25.0, 25.0)),
    "geology-evidence": (lambda tmp_path: _evidence(tmp_path, "geology_basins"), BASIN.bounds),
    "influence-evidence": (lambda tmp_path: _evidence(tmp_path, "influence_features"), OUTLET_BOUNDS),
    "terrain-delineate-roll-call": (_roll_call, OUTLET_BOUNDS),
}  # fmt: skip


@pytest.mark.parametrize("writer", WRITERS)
def test_a_site_selection_geojson_holds_wgs84_lon_lat_and_no_crs_member(tmp_path, writer):
    write, project_bounds = WRITERS[writer]
    path = write(tmp_path)

    payload = json.loads(path.read_text())
    frame = gpd.read_file(path)

    assert "crs" not in payload
    assert frame.crs == "EPSG:4326"
    west, south, east, north = frame.total_bounds
    assert -180.0 <= west <= east <= 180.0 and -90.0 <= south <= north <= 90.0
    # GDAL rounds the roll call to 7 decimals (RFC 7946), about a centimetre.
    assert tuple(frame.to_crs(L93).total_bounds) == pytest.approx(project_bounds, abs=0.01)
    if writer != "terrain-delineate-roll-call":
        assert (payload["hydromodpy_coordinate_crs"], payload["hydromodpy_project_crs"]) == ("OGC:CRS84", L93)  # fmt: skip


@pytest.mark.parametrize(
    "write",
    [
        lambda path: write_outlets_geojson(path, [make_catchment(crs="")], selection_id="v1", site_status="selected"),
        lambda path: write_candidate_outlets_geojson(path, [CandidateOutlet("cand_001", X93, Y93, "", "test")]),
        lambda path: _network(path.parent, crs=None),
        lambda path: _evidence(path.parent, "influence_features", crs=""),
        lambda path: _evidence(path.parent, "influence_features", crs="EPSG:999999"),
        lambda path: _evidence(path.parent, "influence_features", crs='LOCAL_CS["local",UNIT["metre",1]]'),
    ],
    ids=["outlets", "candidates", "network", "evidence", "unreadable-crs", "local-frame"],
)  # fmt: skip
def test_a_geojson_feature_without_a_readable_crs_is_refused_by_name(tmp_path, write):
    with pytest.raises(
        ExportError,
        match=r"\.geojson: feature '.+' (has no CRS|names the CRS '.+').*RFC 7946",
    ):
        write(tmp_path / "layer.geojson")


@pytest.mark.parametrize(("layer", "crs"), [("selected_outlets", L93), (None, "EPSG:4326")])
def test_hmp_sites_import_finds_the_project_coordinates_of_the_selected_outlets(
    tmp_path: Path, layer, crs
):
    gpkg = _selection(tmp_path, "site_selection_gpkg")
    path = gpkg if layer else gpkg.parent / "selected_outlets.geojson"

    (row,) = rows_from_layer(path, name_field="site_id", layer=layer).rows

    assert row.crs == crs
    expected = (X93, Y93) if layer else to_wgs84(Point(X93, Y93)).coords[0]
    assert (row.x_outlet, row.y_outlet) == pytest.approx(expected, abs=1e-9)


def test_the_generated_network_is_written_as_stream_segments(tmp_path):
    payload = json.loads(_network(tmp_path).read_text(encoding="utf-8"))

    assert payload["hydromodpy_geometry_role"] == "generated_dem_network"
    assert payload["hydromodpy_project_crs"] == "EPSG:2154"
    assert any(feature["geometry"]["type"] == "LineString" for feature in payload["features"])


def test_the_generated_network_stays_inside_the_search_geometry(tmp_path):
    accumulation = [[90.0, 1.0, 1.0], [90.0, 1.0, 80.0], [90.0, 1.0, 80.0]]

    path = _network(tmp_path, accumulation, search_geometry=box(20.0, 0.0, 30.0, 20.0))

    network = gpd.read_file(path).to_crs(L93)
    assert not network.empty
    assert network.total_bounds[0] >= 20.0 - 1e-6


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

    assert list(frame["site_id"]) == ["a", "b"]
    assert frame.crs == L93
    # A location without a CRS cannot be placed in WGS 84, so the GeoJSON skips it.
    assert [f["properties"]["site_id"] for f in collection["features"]] == ["a"]
    skipped = {item["site_id"]: item["reason"] for item in collection["hydromodpy_skipped_observations"]}  # fmt: skip
    assert skipped == {"b": "missing_provider_crs"} | dict.fromkeys("cdef", "missing_provider_location")  # fmt: skip
    assert list(frame.geometry.x) == [1.0, 3.0]
    assert collection["features"][0]["properties"]["observation_crs"] == L93
    assert geospatial.write_vector_layer(frame, tmp_path / "obs.gpkg", fmt="gpkg").is_file()
    parquet = geospatial.write_vector_layer(frame, tmp_path / "obs.parquet", fmt="geoparquet")
    assert gpd.read_parquet(parquet).crs == L93


def test_no_observation_point_writes_no_file(tmp_path):
    empty = observation_points_gdf(ROWS[2:])
    assert geospatial.write_vector_layer(empty, tmp_path / "obs.gpkg", fmt="gpkg") is None
    assert geospatial.write_vector_layer(empty, tmp_path / "obs.parquet", fmt="geoparquet") is None
    assert not list(tmp_path.iterdir())
