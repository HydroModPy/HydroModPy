"""write_selection_result writes the tables, vectors and decisions of a selection."""

from __future__ import annotations

import csv
import json

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from hydromodpy.spatial.site_selection.config import AreaCriteriaConfig
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
    write_point_geojson,
    write_vector_layer,
)

pytestmark = pytest.mark.fast

X, Y = 350000.0, 6810000.0
SELECTED = SelectionDecision(
    site_id="site_001",
    selection_principle="criteria_crossing",
    selected=True,
    decision_stage="selection",
    decision_reason="selected",
)


def _site(**fields):
    return make_catchment("site_001", x=X, y=Y, area_km2=101.5, **fields)


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_site_record_carries_the_site_catalog_fields():
    row = site_record_from_catchment(_site(), selection_id="selection_v1", region_id="Bretagne")

    assert (row["site_id"], row["source_selection_id"], row["region_id"]) == (
        "site_001", "selection_v1", "Bretagne",
    )  # fmt: skip
    assert (row["x_outlet"], row["area_km2"], row["crs"]) == (X, 101.5, L93)
    assert (row["gauge"], row["enabled"]) == ("", True)


def test_the_core_files_are_written_and_read_back(tmp_path):
    component = evaluate_area_criterion(
        site_id="site_001",
        area_km2=101.5,
        config=AreaCriteriaConfig(mode="report_only"),
        selection_principle="criteria_crossing",
    )
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

    paths = write_selection_result(
        tmp_path / "a", result, selection_id="v1", write_selected=False, write_rejected=False
    )
    assert {"selected_sites_csv", "rejected_sites_csv"}.isdisjoint(paths)
    assert paths["selected_basins_geojson"].is_file()

    empty = write_selection_result(tmp_path / "c", make_selection(), selection_id="v1", write_geopackage=True)  # fmt: skip
    assert "site_selection_gpkg" not in empty

    paths = write_selection_result(tmp_path / "b", result, selection_id="v1", write_geojson=False)
    assert not any(key.endswith("_geojson") for key in paths)
    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == SELECTED_SITES_FIELDS == list(SELECTED_SITES_SCHEMA)


def test_the_snapped_outlet_replaces_the_original_one(tmp_path):
    snap = write_point_geojson(tmp_path / "outlet_snap.geojson", coordinates=[X + 30.0, Y + 40.0])
    result = make_selection([_site(outlet_snap_shp=str(snap))])

    paths = write_selection_result(tmp_path / "out", result, selection_id="selection_v1")

    feature = json.loads(paths["selected_outlets_geojson"].read_text())["features"][0]
    assert feature["geometry"]["coordinates"] == [X + 30.0, Y + 40.0]
    properties = feature["properties"]
    assert properties["outlet_geometry_source"] == "snapped"
    assert (properties["outlet_original_x"], properties["x_outlet_snapped"]) == (X, X + 30.0)
    assert properties["outlet_snap_distance_m"] == pytest.approx(50.0)
    row = _rows(paths["selected_sites_csv"])[0]
    assert (row["x_outlet_snapped"], float(row["outlet_snap_distance_m"])) == ("350030.0", 50.0)


def test_every_basin_export_skips_the_same_unreadable_basins(tmp_path):
    unreadable = tmp_path / "unreadable.gpkg"
    unreadable.write_text("not a vector", encoding="utf-8")
    basins = {
        "missing": tmp_path / "nowhere.gpkg",
        "unreadable": unreadable,
        "empty": write_vector_layer(tmp_path / "empty.gpkg", [Polygon()]),
        "no_rows": write_vector_layer(tmp_path / "no_rows.gpkg", []),
        "l93": write_vector_layer(tmp_path / "l93.gpkg", [box(X, Y, X + 1000.0, Y + 800.0)]),
        "wgs84": write_vector_layer(
            tmp_path / "wgs84.gpkg", [box(-1.66, 48.12, -1.65, 48.13)], crs="EPSG:4326"
        ),
        "no_crs": write_vector_layer(
            tmp_path / "no_crs.gpkg", [box(X, Y, X + 50, Y + 50)], crs=None
        ),
    }
    sites = [
        make_catchment(name, x=X, y=Y, watershed_shp=str(path)) for name, path in basins.items()
    ]
    result = make_selection(sites)

    paths = write_selection_result(
        tmp_path / "out", result, selection_id="v1", write_geopackage=True, write_geoparquet=True
    )

    collection = json.loads(paths["selected_basins_geojson"].read_text())
    skipped = {item["site_id"]: item["reason"] for item in collection["hydromodpy_skipped_basins"]}
    assert skipped["missing"] == "missing_watershed_vector"
    assert skipped["unreadable"].startswith("read_failed:")
    assert [feature["properties"]["site_id"] for feature in collection["features"]] == [
        "l93", "wgs84", "no_crs",
    ]  # fmt: skip
    assert collection["hydromodpy_coordinate_crs"] == "mixed"
    assert "crs" not in collection
    for frame in (
        gpd.read_file(paths["site_selection_gpkg"], layer="selected_basins"),
        gpd.read_parquet(paths["selected_basins_geoparquet"]),
    ):
        assert frame.crs == L93
        assert list(frame["site_id"]) == ["l93", "wgs84", "no_crs"]
        assert frame.total_bounds[0] > 300_000.0
