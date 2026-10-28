from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.spatial.administrative.france import bbox_for_departments, bbox_for_regions
from hydromodpy.spatial.site_selection.candidates.pipeline import (
    build_dem_area_light_candidates,
    build_generated_network_candidates,
    build_station_candidate_outlets,
    site_selection_search_geometry,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from tests._helpers.site_selection_cases import (
    make_point_record,
    selection_section,
    site_flow_products,
    write_accumulation_raster,
    write_polygon_geojson,
)

pytestmark = pytest.mark.fast
gpd = pytest.importorskip("geopandas")


def _config(tmp_path, profile="gauged", **tables) -> SiteSelectionConfig:
    return SiteSelectionConfig.model_validate(
        selection_section(profile, output_root=tmp_path / "out", **tables)
    )


def test_station_candidates_are_thinned_by_the_configured_distance(tmp_path):
    records = [
        make_point_record("A", x=0.0, y=0.0, n_values=5),
        make_point_record("B", x=500.0, y=0.0, n_values=2),
        make_point_record("C", x=2500.0, y=0.0, n_values=1),
    ]
    thinned = _config(tmp_path, outlets={"min_distance_between_outlets_km": 1.0})

    for cfg, expected in ((thinned, ["A", "C"]), (_config(tmp_path), ["A", "B", "C"])):
        candidates = build_station_candidate_outlets(records, config=cfg, target_crs="EPSG:2154")
        assert [one.source_feature_id for one in candidates] == expected


BOWTIE = [[-1.7, 48.0], [-1.6, 48.1], [-1.6, 48.0], [-1.7, 48.1], [-1.7, 48.0]]


@pytest.mark.parametrize(
    ("territory", "bounds"),
    [
        ({"mode": "bbox", "bbox": [0.0, 0.0, 10.0, 20.0]}, (0.0, 0.0, 10.0, 20.0)),
        ({"mode": "admin_departments", "departments": ["35"]}, bbox_for_departments(["35"])),
        ({"mode": "admin_regions", "regions": ["Bretagne"]}, bbox_for_regions(["Bretagne"])),
    ],
)
def test_the_search_geometry_fills_the_territory_box(tmp_path, territory, bounds):
    cfg = _config(tmp_path, territory={"country": "FR", **territory})

    geometry = site_selection_search_geometry(cfg, target_crs="EPSG:2154")

    assert geometry.is_valid
    assert geometry.bounds == pytest.approx(bounds)


def test_a_territory_polygon_is_reprojected_and_made_valid(tmp_path):
    polygon = write_polygon_geojson(tmp_path / "zone.geojson", coordinates=BOWTIE)
    cfg = _config(tmp_path, territory={"mode": "polygon_file", "polygon_file": polygon})

    geometry = site_selection_search_geometry(cfg, target_crs="EPSG:2154")

    assert geometry.is_valid and geometry.area > 0.0
    assert 300_000.0 < geometry.centroid.x < 400_000.0


@pytest.mark.parametrize(
    "territory",
    [
        {"mode": "bbox", "bbox": [0.0, 0.0, 1.0, 1.0], "clip_to_territory": False},
        {"mode": "admin_departments", "departments": ["35"], "country": "BE"},
    ],
)
def test_no_search_geometry_without_a_french_or_clipped_territory(tmp_path, territory):
    cfg = _config(tmp_path, territory=territory)
    assert site_selection_search_geometry(cfg, target_crs=None) is None


NETWORK = np.array([[1.0, 50.0, 200.0]])


def _generated(tmp_path, **outlets):
    flow = site_flow_products(write_accumulation_raster(tmp_path / "acc.tif", NETWORK))
    cfg = _config(tmp_path, "custom", outlets={"max_generated_candidates": 1, **outlets})
    return build_generated_network_candidates(
        config=cfg, flow_products=flow, target_crs=None, root=tmp_path, search_geometry=None
    )


def test_generated_candidates_are_scored_against_a_custom_network(tmp_path):
    network = tmp_path / "network.gpkg"
    gpd.GeoDataFrame(geometry=[LineString([(0.0, 25.0), (30.0, 25.0)])], crs="EPSG:2154").to_file(
        network
    )

    result = _generated(tmp_path, reference_network_source="custom", reference_network_path=network)

    (candidate,) = result.candidates
    assert candidate.attributes["reference_network_distance_m"] == 20.0
    assert result.evidence[0].reference_network_status == "within_reference_network_tolerance"
    assert result.reference_bundle.source == "custom"


def test_generated_candidates_snap_on_bd_topage_fetched_once(tmp_path, monkeypatch):
    from hydromodpy.data.variables.hydrography.apis import bdtopage

    fetched = []
    river = gpd.GeoDataFrame(geometry=[LineString([(0.0, 5.0), (30.0, 5.0)])], crs="EPSG:2154")

    def fetch(cfg, bbox_wgs84):
        fetched.append(bbox_wgs84)
        return river.to_crs("EPSG:4326")

    monkeypatch.setattr(bdtopage, "fetch", fetch)
    for _ in range(2):
        result = _generated(tmp_path, snap_strategy="bdtopage_then_dem")

    assert len(fetched) == 1
    assert result.reference_bundle.feature_count == 1
    assert result.candidates[0].attributes["reference_network_distance_m"] < 1e-6


def test_a_reference_network_without_an_outlet_crs_is_refused(tmp_path):
    flow = site_flow_products(write_accumulation_raster(tmp_path / "acc.tif", NETWORK))
    cfg = _config(tmp_path, "custom", outlets={"snap_strategy": "bdtopage_then_dem"})

    with pytest.raises(ValueError, match="requires a projected outlet CRS"):
        build_generated_network_candidates(
            config=cfg,
            flow_products=flow,
            target_crs=None,
            root=tmp_path,
            search_geometry=Polygon(),
        )


def test_the_dem_area_scan_needs_its_window(tmp_path):
    with pytest.raises(ValueError, match="requires dem_area_light config"):
        build_dem_area_light_candidates(
            config=_config(tmp_path, "custom"),
            flow_products=None,
            target_crs=None,
            root=tmp_path,
            search_geometry=None,
        )
