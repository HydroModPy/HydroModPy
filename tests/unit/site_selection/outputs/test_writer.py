"""write_selection_result writes the tables, vectors and decisions of a selection."""

from __future__ import annotations

import csv
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

from hydromodpy.spatial.site_selection.config.criteria_config import AreaCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.area import evaluate_area_criterion
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionDecision
from hydromodpy.spatial.site_selection.outputs.schemas import (
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
)
from hydromodpy.spatial.site_selection.outputs.writer import write_selection_result
from tests._helpers.site_selection_cases import (
    L93,
    make_catchment,
    make_selection,
    to_wgs84,
    write_basin,
    write_point_geojson,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

X, Y = 350000.0, 6810000.0
SELECTED = SelectionDecision("site_001", "criteria_crossing", True, "selection", "selected")


def _site(**fields):
    return make_catchment("site_001", x=X, y=Y, area_km2=101.5, **fields)


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


BOWTIE = Polygon([(0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0), (0.0, 0.0)])
LAYERS = ("selected_outlets", "rejected_outlets", "selected_basins", "rejected_basins")


@pytest.mark.parametrize("basin", [box(0.0, 0.0, 10.0, 8.0), BOWTIE], ids=["valid", "bowtie"])
def test_the_selection_layers_open_in_their_crs_with_valid_basins(tmp_path, basin):
    basin_path = str(write_vector_layer(tmp_path / "basin.gpkg", [basin]))
    attributes = {"reference_network_source": "bdtopage"}
    selected = make_catchment(x=5.0, y=4.0, watershed_shp=basin_path, attributes=attributes)
    rejected = make_catchment("site_002", x=50.0, y=4.0, watershed_shp=basin_path)
    result = make_selection([selected], [rejected])
    write = dict(selection_id="v1", write_geopackage=True, write_geoparquet=True)

    write_selection_result(tmp_path / "out", result, **write)
    paths = write_selection_result(tmp_path / "out", result, **write)

    assert set(gpd.list_layers(paths["site_selection_gpkg"])["name"]) == set(LAYERS)
    outlets = gpd.read_file(paths["site_selection_gpkg"], layer="selected_outlets")
    assert (outlets.crs, outlets.loc[0, "site_id"]) == (L93, "site_001")
    assert outlets.loc[0, "reference_network_source"] == "bdtopage"
    for key in LAYERS:
        frame = gpd.read_parquet(paths[f"{key}_geoparquet"])
        assert frame.crs == L93
        assert frame.geometry.is_valid.all()
    basins = gpd.read_file(paths["site_selection_gpkg"], layer="selected_basins")
    assert basins.geometry.iloc[0].is_valid
    assert basins.geometry.iloc[0].area == pytest.approx(80.0 if basin.is_valid else 50.0)
    assert json.loads(paths["selected_basins_geojson"].read_text())["features"]


def test_a_site_record_carries_the_site_catalog_fields():
    row = site_record_from_catchment(_site(), selection_id="selection_v1", region_id="Bretagne")

    keys = ("site_id", "source_selection_id", "region_id", "x_outlet", "area_km2", "crs", "gauge")
    assert [row[key] for key in keys] == ["site_001", "selection_v1", "Bretagne", X, 101.5, L93, ""]
    assert row["enabled"] is True


def test_the_core_files_are_written_and_read_back(tmp_path):
    component = evaluate_area_criterion(
        site_id="site_001", area_km2=101.5, config=AreaCriteriaConfig(mode="report_only"),
        selection_principle="criteria_crossing",
    )  # fmt: skip
    result = make_selection([_site()], decisions=[SELECTED], components=[component])

    paths = write_selection_result(tmp_path, result, selection_id="selection_v1", region_id="BZH")

    assert all(path.is_file() for path in paths.values())
    assert _rows(paths["selected_sites_csv"])[0]["source_selection_id"] == "selection_v1"
    assert _lines(paths["criteria_components_jsonl"])[0]["criterion_id"] == "area"
    records = _lines(paths["site_selection_decisions_jsonl"])
    assert {record["criterion_id"] for record in records} == {"area", "final_selection"}
    summary = _rows(paths["site_selection_decisions_csv"])[0]
    assert (summary["catchment_id"], summary["global_decision"]) == ("site_001", "ACCEPT")
    feature = json.loads(paths["selected_outlets_geojson"].read_text())["features"][0]
    assert (feature["geometry"]["type"], feature["properties"]["outlet_crs"]) == ("Point", L93)


def test_the_switches_leave_out_the_site_tables_or_the_geojson(tmp_path):
    result = make_selection([_site()], decisions=[SELECTED])

    paths = write_selection_result(tmp_path / "a", result, selection_id="v1", write_selected=False, write_rejected=False)  # fmt: skip
    assert {"selected_sites_csv", "rejected_sites_csv"}.isdisjoint(paths)
    assert paths["selected_basins_geojson"].is_file()

    empty = write_selection_result(tmp_path / "c", make_selection(), selection_id="v1", write_geopackage=True)  # fmt: skip
    assert "site_selection_gpkg" not in empty

    paths = write_selection_result(tmp_path / "b", result, selection_id="v1", write_geojson=False)
    assert not any(key.endswith("_geojson") for key in paths)
    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == SELECTED_SITES_FIELDS == list(SELECTED_SITES_SCHEMA)


def test_the_snapped_outlet_replaces_the_original_one(tmp_path):
    lon_lat = list(to_wgs84(Point(X + 30.0, Y + 40.0)).coords[0])
    snap = write_point_geojson(tmp_path / "outlet_snap.geojson", coordinates=lon_lat)
    result = make_selection([_site(outlet_snap_shp=str(snap))])

    paths = write_selection_result(tmp_path / "out", result, selection_id="selection_v1")

    feature = json.loads(paths["selected_outlets_geojson"].read_text())["features"][0]
    assert feature["geometry"]["coordinates"] == pytest.approx(lon_lat, abs=1e-9)
    properties = feature["properties"]
    assert properties["outlet_geometry_source"] == "snapped"
    assert properties["outlet_original_x"] == X
    assert properties["x_outlet_snapped"] == pytest.approx(X + 30.0, abs=1e-6)
    assert properties["outlet_snap_distance_m"] == pytest.approx(50.0)
    row = _rows(paths["selected_sites_csv"])[0]
    assert (float(row["x_outlet_snapped"]), float(row["outlet_snap_distance_m"])) == pytest.approx((X + 30.0, 50.0))  # fmt: skip


def test_a_selection_mixing_a_snapped_and_an_unsnapped_outlet_writes_nulls_in_its_layers(tmp_path):
    snap = str(write_vector_layer(tmp_path / "snap.gpkg", [Point(X + 30.0, Y + 40.0)]))
    basin = write_basin(tmp_path)
    sites = [
        make_catchment("snapped", x=X, y=Y, outlet_snap_shp=snap, watershed_shp=basin),
        make_catchment("unsnapped", x=X, y=Y, area_km2=None, watershed_shp=basin),
    ]
    write = dict(selection_id="v1", write_geopackage=True, write_geoparquet=True)

    paths = write_selection_result(tmp_path / "out", make_selection(sites), **write)

    for layer in ("selected_outlets", "selected_basins"):
        for frame in (
            gpd.read_parquet(paths[f"{layer}_geoparquet"]),
            gpd.read_file(paths["site_selection_gpkg"], layer=layer),
        ):
            by_site = frame.set_index("site_id")
            assert by_site.loc["snapped", "x_outlet_snapped"] == pytest.approx(X + 30.0)
            assert by_site.loc["snapped", "area_km2"] == pytest.approx(100.0)
            for key in ("x_outlet_snapped", "outlet_snap_distance_m", "area_km2"):
                assert pd.isna(by_site.loc["unsnapped", key])
    assert _rows(paths["selected_sites_csv"])[1]["x_outlet_snapped"] == ""


def test_every_basin_export_skips_the_same_unreadable_basins(tmp_path):
    unreadable = tmp_path / "unreadable.gpkg"
    unreadable.write_text("not a vector", encoding="utf-8")
    kinds = ("empty", "no_rows", "l93", "wgs84", "no_crs")
    basins = {"missing": tmp_path / "nowhere.gpkg", "unreadable": unreadable}
    basins |= {kind: write_basin(tmp_path, kind) for kind in kinds}
    sites = [make_catchment(one, x=X, y=Y, watershed_shp=str(path)) for one, path in basins.items()]
    write = dict(selection_id="v1", write_geopackage=True, write_geoparquet=True)

    paths = write_selection_result(tmp_path / "out", make_selection(sites), **write)

    collection = json.loads(paths["selected_basins_geojson"].read_text())
    skipped = {item["site_id"]: item["reason"] for item in collection["hydromodpy_skipped_basins"]}
    assert skipped["missing"] == "missing_watershed_vector"
    assert skipped["unreadable"].startswith("read_failed:")
    assert [feature["properties"]["site_id"] for feature in collection["features"]] == list(
        kinds[2:]
    )
    assert (collection["hydromodpy_coordinate_crs"], collection["hydromodpy_project_crs"]) == ("OGC:CRS84", "mixed")  # fmt: skip
    assert "crs" not in collection
    for frame in (
        gpd.read_file(paths["site_selection_gpkg"], layer="selected_basins"),
        gpd.read_parquet(paths["selected_basins_geoparquet"]),
    ):
        assert frame.crs == L93
        assert list(frame["site_id"]) == list(kinds[2:])
        assert frame.total_bounds[0] > 300_000.0
