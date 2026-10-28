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
from hydromodpy.spatial.site_selection.candidates.generation import (
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult
from hydromodpy.spatial.site_selection.evidence.context import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.hydrology.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts
from hydromodpy.spatial.site_selection.outputs.evidence_layers import write_evidence_layer
from hydromodpy.spatial.site_selection.outputs.writer import (
    write_observation_points_geojson,
    write_selection_result,
)
from tests._helpers.site_selection_cases import (
    write_accumulation_raster,
)
from tests._helpers.terrain_doubles import fake_flow_products

pytestmark = pytest.mark.fast

X, Y = 350_000.0, 6_810_000.0
"""A Lambert-93 point in Brittany, which no WGS 84 reading can mistake."""
L93 = "EPSG:2154"
BASIN = box(X - 500.0, Y - 400.0, X + 500.0, Y + 400.0)


def _selection(tmp_path: Path, key: str) -> Path:
    basin = tmp_path / "basin.gpkg"
    gpd.GeoDataFrame({"name": ["basin"]}, geometry=[BASIN], crs=L93).to_file(basin, driver="GPKG")
    catchment = DelineatedCatchment(
        site_id="site_001",
        outlet=CandidateOutlet("cand_001", X, Y, L93, "test"),
        watershed_shp=str(basin),
        area_km2=0.8,
    )
    result = SelectionResult(
        selected=[catchment], rejected=[], decisions=[], criteria_components=[]
    )
    return write_selection_result(tmp_path / "out", result, selection_id="selection_v1")[key]


def _observations(tmp_path: Path) -> Path:
    evidence = ObservationEvidence(
        site_id="site_001",
        observation_type="flow_station",
        source_dataset="hubeau",
        feature_id="J001401001",
        evidence_json={"provider_location": {"x": X, "y": Y, "crs": L93}},
    )
    return write_observation_points_geojson(tmp_path / "observation_points.geojson", [evidence])


def _candidates(tmp_path: Path) -> Path:
    outlet = CandidateOutlet("cand_001", X, Y, L93, "test")
    return write_candidate_outlets_geojson(tmp_path / "candidates.geojson", [outlet])


def _network(tmp_path: Path) -> Path:
    acc = np.array([[1.0, 1.0, 1.0], [1.0, 50.0, 60.0], [1.0, 1.0, 70.0]])
    acc_path = write_accumulation_raster(tmp_path / "acc.tif", acc)
    flow_products = SiteSelectionFlowProducts(
        products=fake_flow_products(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )
    return write_generated_network_geojson(
        tmp_path / "network.geojson",
        flow_products=flow_products,
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
    )


def _geology(tmp_path: Path) -> Path:
    evidence = GeologyEvidence(
        site_id="site_001",
        source_layer="geology",
        geology_class="granite",
        area_fraction=1.0,
        area_km2=0.8,
        feature_count=1,
        geometry=BASIN,
        crs=L93,
    )
    return write_evidence_layer(
        tmp_path / "geology.geojson", [evidence], role="geology_basins", fmt="geojson"
    )


def _influence(tmp_path: Path) -> Path:
    evidence = InfluenceEvidence(
        site_id="site_001",
        influence_type="dam",
        source_layer="dams",
        geometry=Point(X, Y),
        crs=L93,
    )
    return write_evidence_layer(
        tmp_path / "influence.geojson", [evidence], role="influence_features", fmt="geojson"
    )


WRITERS: dict[str, Callable[[Path], Path]] = {
    "selected-outlets": lambda tmp_path: _selection(tmp_path, "selected_outlets_geojson"),
    "selected-basins": lambda tmp_path: _selection(tmp_path, "selected_basins_geojson"),
    "observation-points": _observations,
    "candidate-outlets": _candidates,
    "generated-network": _network,
    "geology-evidence": _geology,
    "influence-evidence": _influence,
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

    assert (row.x_outlet, row.y_outlet) == (X, Y)
    assert row.crs == L93


@pytest.mark.parametrize("label", ["", "mixed", 'LOCAL_CS["engineering"]'])
def test_a_crs_without_an_epsg_code_writes_no_crs_member(label: str):
    assert geojson_crs_member(label) == {}
