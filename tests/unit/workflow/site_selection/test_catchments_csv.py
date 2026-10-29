from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.data.variables.hydrography.apis import bdtopage
from hydromodpy.spatial.site_selection.candidates.pipeline import site_selection_search_geometry
from hydromodpy.workflow.site_selection.catchments_csv import select_delineated_catchments_from_csv
from hydromodpy.workflow.site_selection.data_loading import load_site_selection_config
from hydromodpy.workflow.site_selection.dem_request import load_data_dem_config_for_site_selection
from tests._helpers.site_selection_cases import (
    delineation_spy,
    dem_loader_spy,
    flow_spy,
    selection_section,
    write_polygon_geojson,
    write_selection_toml,
)

pytestmark = pytest.mark.fast

DATA_DEM = {"types": ["dem"], "dem": {"sources": [{"source": "custom", "path": "dem.tif"}]}}
DELINEATE = {"delineate_from_outlets": True}


def _select(tmp_path: Path, rows: str = "site_001,10,20,100", *, data=None, loader=None, **tables):
    """Write the selection and its CSV, then select with spies on every builder."""
    (tmp_path / "dem.tif").write_text("dem placeholder", encoding="utf-8")
    (tmp_path / "catchments.csv").write_text(f"site_id,x,y,area_km2\n{rows}\n", encoding="utf-8")
    top = {} if data is None else {"data": data}
    config_path = write_selection_toml(tmp_path, selection_section(**tables), **top)
    spies: dict = {"dem": [], "flow": {}, "delineation": []}
    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path, catchments_csv=tmp_path / "catchments.csv",
        flow_products_builder=flow_spy(spies["flow"]),
        delineation_builder=delineation_spy(spies["delineation"], size=10.0),
        area_reader=lambda _path: 100.0, region_id="BZH",
        dem_loader=loader or dem_loader_spy(tmp_path / "dem.tif", spies["dem"]),
    )  # fmt: skip
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    return result, paths, manifest, spies


def test_the_csv_sites_are_selected_and_written_with_their_region(tmp_path):
    result, paths, manifest, _ = _select(tmp_path, "site_ok,0,0,100\nsite_bad,1,1,50")
    assert [site.site_id for site in result.selected] == ["site_ok"]
    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["site_id"], row["region_id"]) for row in rows] == [("site_ok", "BZH")]
    assert "map_dem_path" not in manifest["flow_products"]


@pytest.mark.parametrize(
    ("dem", "data", "expected"),
    [
        ({"path": "dem.tif"}, None, {"dem_usage": "review_map_background"}),
        ({"source": "data"}, DATA_DEM, {"dem_usage": "review_map_background"}),
        ({"path": "dem.tif", "map_background_extent": "none"}, None, {}),
    ],
)
def test_pre_delineated_sites_take_a_dem_for_the_review_map(tmp_path, dem, data, expected):
    _, _, manifest, spies = _select(tmp_path, dem=dem, data=data)

    if expected:
        assert manifest["flow_products"]["map_dem_path"] == str(tmp_path / "dem.tif")
    assert {key: manifest["flow_products"].get(key) for key in expected} == expected
    assert len(spies["dem"]) == (1 if data else 0)


@pytest.mark.parametrize(
    ("dem", "data", "map_dem_loads"),
    [
        ({"path": "dem.tif"}, None, 0),
        ({"source": "data", "map_background_extent": "territory"}, DATA_DEM, 1),
        ({"source": "data", "map_background_extent": "none"}, DATA_DEM, 0),
        ({"source": "ign_geoplateforme_dem"}, None, 0),
        ({"source": "data", "request_extent": "outlets"}, DATA_DEM, 0),
    ],
)
def test_outlets_are_delineated_on_the_dem_the_file_names(tmp_path, dem, data, map_dem_loads):
    result, _, manifest, spies = _select(tmp_path, input=DELINEATE, dem=dem, data=data)

    assert spies["flow"]["dem_init_path"] == tmp_path / "dem.tif"
    assert manifest["flow_products"]["dem_path"] == str(tmp_path / "dem.tif")
    assert result.selected[0].watershed_shp.endswith("watershed.geojson")
    expected_map = None if dem.get("map_background_extent") == "none" else str(tmp_path / "dem.tif")
    assert manifest["flow_products"].get("map_dem_path") == expected_map
    assert len(spies["dem"]) == (0 if "path" in dem else 1) + map_dem_loads


@pytest.mark.parametrize("source", ["custom", "bdtopage"])
def test_outlets_snap_to_a_reference_network_before_the_dem(tmp_path, monkeypatch, source):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString

    river = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])], crs="EPSG:2154")
    river.to_file(tmp_path / "river.gpkg")
    monkeypatch.setattr(bdtopage, "fetch", lambda cfg, bbox: river.to_crs("EPSG:4326"))
    outlets = {
        "snap_strategy": "bdtopage_then_dem", "reference_network_source": source,
        "reference_network_path": "river.gpkg", "reference_network_max_distance_m": 50.0,
    }  # fmt: skip

    result, _, manifest, spies = _select(
        tmp_path, "site_001,25,12,100", input=DELINEATE, dem={"path": "dem.tif"}, outlets=outlets
    )

    call = spies["delineation"][0]
    assert (call["x_outlet"], call["y_outlet"]) == pytest.approx((25.0, 0.0), abs=1e-6)
    assert [site.site_id for site in result.selected] == ["site_001"]
    assert manifest["outlets"]["snap_strategy"] == "bdtopage_then_dem"
    assert manifest["flow_products"]["reference_network"]["source"] == source


def test_delineating_outlets_without_a_dem_says_where_to_look(tmp_path):
    with pytest.raises(ConfigMissingError, match="delineate_from_outlets=true requires"):
        _select(tmp_path, input=DELINEATE)
    with pytest.raises(ConfigError, match="loading DEM data.*did not return any field"):
        _select(tmp_path, input=DELINEATE, data=DATA_DEM, loader=lambda **_: [])


BOWTIE = [[-1.7, 48.0], [-1.6, 48.1], [-1.6, 48.0], [-1.7, 48.1], [-1.7, 48.0]]


@pytest.mark.parametrize(
    "territory",
    [
        {"mode": "bbox", "bbox": [0.0, 0.0, 10000.0, 10000.0]},
        {"mode": "admin_regions", "regions": ["Bretagne"]},
        {"mode": "admin_regions", "regions": ["Bretagne"], "country": "fr"},
        {"mode": "admin_departments", "departments": ["35"]},
        {"mode": "polygon_file", "polygon_file": "zone.geojson"},
    ],
)
def test_the_dem_request_covers_the_search_geometry_and_its_margin(tmp_path, territory):
    write_polygon_geojson(tmp_path / "zone.geojson", coordinates=BOWTIE)
    dem = {"source": "data", "margin_km": 2.0}

    _, _, _, spies = _select(tmp_path, input=DELINEATE, dem=dem, territory=territory, data=DATA_DEM)

    cfg = load_site_selection_config(tmp_path / "selection.toml")
    xmin, ymin, xmax, ymax = site_selection_search_geometry(cfg, target_crs="EPSG:2154").bounds
    expected = (xmin - 2000.0, ymin - 2000.0, xmax + 2000.0, ymax + 2000.0)
    if territory["mode"] == "bbox":
        assert expected == (-2000.0, -2000.0, 12000.0, 12000.0)
    assert spies["dem"][0]["project_extent"] == pytest.approx(expected)


def test_a_territory_outside_france_asks_the_dem_around_the_outlets(tmp_path):
    territory = {"mode": "admin_regions", "regions": ["Wallonie"], "country": "BE"}
    dem = {"source": "data", "margin_km": 1.0}

    _, _, _, spies = _select(
        tmp_path, "a,10,20,100\nb,110,220,100", input=DELINEATE, dem=dem, territory=territory,
        data=DATA_DEM,
    )  # fmt: skip

    assert spies["dem"][0]["project_extent"] == (-990.0, -980.0, 1110.0, 1220.0)


def test_the_data_dem_section_resolves_its_path_against_the_file(tmp_path):
    config_path = write_selection_toml(tmp_path, selection_section(), data=DATA_DEM)

    assert load_data_dem_config_for_site_selection(config_path).sources[0].path == (
        tmp_path / "dem.tif"
    )
