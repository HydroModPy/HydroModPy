from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.workflow.site_selection.build_from_toml import (
    build_dem_area_light_site_selection_from_toml,
    build_generated_site_selection_from_toml,
    build_observed_site_selection_from_toml,
    build_site_selection_from_hydrometry_config,
)
from tests._helpers.site_selection_cases import (
    delineation_spy,
    dem_loader_spy,
    flow_spy,
    make_config,
    make_record,
    make_wgs84_hubeau_record,
    selection_section,
    write_accumulation_raster,
    write_selection_toml,
)

pytestmark = pytest.mark.fast

HUBEAU = {"date_start": "2020-01-01", "date_end": "2020-01-02", "sources": [{"source": "hubeau"}]}
TERRITORY = {"mode": "bbox", "bbox": [300000.0, 6800000.0, 310000.0, 6810000.0]}


def _data_dem(path: str = "data/dem.tif") -> dict:
    return {"types": ["dem"], "dem": {"sources": [{"source": "custom", "path": path}]}}


def _observed(tmp_path: Path, *, dem: dict | None = None, territory=TERRITORY) -> Path:
    section = selection_section(
        "gauged", input={"mode": "hydrometry"}, dem=dem or {"source": "data"}, territory=territory
    )
    return write_selection_toml(tmp_path, section, hydrometry=HUBEAU, data=_data_dem())


def _fake_dem(tmp_path: Path) -> Path:
    dem = tmp_path / "data" / "dem.tif"
    dem.parent.mkdir(exist_ok=True)
    dem.write_text("fake dem", encoding="utf-8")
    return dem


def test_hydrometry_records_from_the_loader_feed_the_build(tmp_path):
    calls: dict = {}
    config = HydrometryConfig.model_validate(HUBEAU)

    result = build_site_selection_from_hydrometry_config(
        config=make_config(tmp_path),
        hydrometry_config=config,
        hydrometry_loader=lambda **kwargs: calls.update(kwargs) or [make_record("J123456701")],
        flow_products_builder=flow_spy(),
        delineation_builder=delineation_spy(),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert calls["config"] is config
    assert [candidate.source_feature_id for candidate in result.candidates] == ["J123456701"]
    assert result.output_paths == {}


@pytest.mark.parametrize(
    ("dem", "territory", "dem_extent", "message", "station_x"),
    [
        ({"source": "data"}, TERRITORY, tuple(TERRITORY["bbox"]), "loading hydrometry", 352000.0),
        (
            {"source": "data", "request_extent": "outlets", "margin_km": 2.0},
            TERRITORY,
            (350000.0, 6810000.0, 354000.0, 6814000.0),
            "DEM extent from 1 station outlets",
            352000.0,
        ),
        (
            {"source": "data", "request_extent": "outlets"},
            {**TERRITORY, "country": None},
            tuple(TERRITORY["bbox"]),
            "DEM extent falls back to territory",
            -1.65,
        ),
    ],
    ids=["territory", "station_outlets", "no_french_outlets"],
)
def test_an_observed_selection_asks_the_stations_then_the_dem_for_its_extent(
    tmp_path, dem, territory, dem_extent, message, station_x
):
    dem_path = _fake_dem(tmp_path)
    order, dem_calls, hydrometry_calls, flow_calls, progress = [], [], [], {}, []

    def hydrometry_loader(**kwargs):
        order.append("hydrometry")
        hydrometry_calls.append(kwargs)
        return [make_wgs84_hubeau_record("J123456701")]

    def dem_loader(**kwargs):
        order.append("dem")
        return dem_loader_spy(dem_path, dem_calls)(**kwargs)

    result = build_observed_site_selection_from_toml(
        config_path=_observed(tmp_path, dem=dem, territory=territory),
        dem_loader=dem_loader,
        hydrometry_loader=hydrometry_loader,
        flow_products_builder=flow_spy(flow_calls),
        delineation_builder=delineation_spy(),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
        progress_callback=progress.append,
    )

    assert order == ["hydrometry", "dem"]
    assert dem_calls[0]["project_extent"] == pytest.approx(dem_extent)
    assert dem_calls[0]["data_root"] == hydrometry_calls[0]["data_root"] == tmp_path / "out/data"
    lon_min, lat_min, lon_max, lat_max = hydrometry_calls[0]["project_extent"]
    assert -3.5 < lon_min < lon_max < -2.0 and 47.5 < lat_min < lat_max < 49.0
    assert flow_calls["dem_init_path"] == dem_path
    assert result.candidates[0].x == station_x
    assert any(message in line for line in progress)
    assert "finished with 1 candidates" in progress[-1]


def _fail(**_kwargs):
    raise OSError("provider down")


@pytest.mark.parametrize(
    ("build", "case", "error", "match"),
    [
        ("hydrometry_config", {}, ConfigError, "loading hydrometry data. data_root=<default>"),
        ("observed", {"hydrometry_loader": _fail}, ConfigError, "loading hydrometry data"),
        ("observed", {"dem_loader": _fail}, ConfigError, "loading DEM data.*OSError"),
        ("observed", {"no_dem": True}, ConfigMissingError, "mode='hydrometry' requires"),
        ("generated", {"dem_loader": _fail}, ConfigError, "Check \\[site_selection.input\\]"),
        ("generated", {"no_dem": True}, ConfigMissingError, "'generated_candidates' or"),
    ],
)
def test_a_selection_whose_data_cannot_be_loaded_says_where_to_look(
    tmp_path, build, case, error, match
):
    if build == "hydrometry_config":
        with pytest.raises(error, match=match):
            build_site_selection_from_hydrometry_config(
                config=make_config(tmp_path),
                hydrometry_config=HydrometryConfig.model_validate(HUBEAU),
                hydrometry_loader=_fail,
            )
        return
    section = selection_section(
        "gauged" if build == "observed" else "custom",
        input={"mode": "hydrometry" if build == "observed" else "generated_candidates"},
        territory=TERRITORY,
    )
    data = {} if case.get("no_dem") else {"data": _data_dem()}
    config_path = write_selection_toml(tmp_path, section, hydrometry=HUBEAU, **data)
    loaders = {"dem_loader": case.get("dem_loader", _fail)}
    if build == "observed":
        builder = build_observed_site_selection_from_toml
        loaders["hydrometry_loader"] = case.get(
            "hydrometry_loader", lambda **_: [make_record("J1")]
        )
    else:
        builder = build_generated_site_selection_from_toml

    with pytest.raises(error, match=match):
        builder(config_path=config_path, **loaders)


def test_an_observed_selection_reads_local_stations_and_dem_through_the_data_store(tmp_path):
    stations = tmp_path / "stations"
    stations.mkdir()
    pd.DataFrame(
        {"id": ["J1"], "x": [305000.0], "y": [6805000.0], "crs": ["EPSG:2154"], "unit": ["m3/s"]}
    ).to_csv(stations / "hydrometry_custom_LOC.csv", index=False)
    pd.DataFrame({"datetime": pd.date_range("2020-01-01", periods=2), "value": [1.0, 2.0]}).to_csv(
        stations / "hydrometry_custom_J1.csv", index=False
    )
    from tests._helpers.geotiffs import write_geotiff

    write_geotiff(
        tmp_path / "data" / "dem.tif", np.ones((4, 4)), origin=(300000.0, 6810000.0), cell=2500.0
    )
    hydrometry = {**HUBEAU, "sources": [{"source": "custom", "path": "stations"}]}
    section = selection_section("gauged", input={"mode": "hydrometry"}, dem={"source": "data"})
    config_path = write_selection_toml(
        tmp_path, section | {"territory": TERRITORY}, hydrometry=hydrometry, data=_data_dem()
    )
    flow_calls: dict = {}

    result = build_observed_site_selection_from_toml(
        config_path=config_path,
        flow_products_builder=flow_spy(flow_calls),
        delineation_builder=delineation_spy(),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert [(one.source_feature_id, one.x, one.y) for one in result.candidates] == [
        ("J1", 305000.0, 6805000.0)
    ]
    assert Path(flow_calls["dem_init_path"]).is_file()
    assert (tmp_path / "out" / "data").is_dir()


@pytest.mark.parametrize("scored", [False, True], ids=["plain", "reference_scored"])
def test_generated_candidates_write_their_audit_and_their_reference_score(tmp_path, scored):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString

    acc = write_accumulation_raster(tmp_path / "acc.tif", np.diag([20.0, 1.0, 30.0]) + 1.0)
    dem = write_accumulation_raster(tmp_path / "data" / "dem.tif", np.ones((3, 3)))
    river = LineString([(0.0, 25.0), (30.0, 25.0)])
    gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154").to_file(tmp_path / "river.gpkg")
    section = selection_section(
        "custom",
        input={"mode": "generated_candidates"},
        dem={"source": "data"},
        strategy={"principle": "criteria_crossing", "primary_axes": ["area"]},
        territory={"mode": "bbox", "regions": [], "bbox": [0.0, 0.0, 30.0, 30.0]},
        hydrology={"network_threshold_area_km2": 0.0001},
        outlets={
            "max_generated_candidates": 2,
            "min_distance_between_outlets_km": 0.01,
            "reference_network_source": "custom",
            "reference_network_path": "river.gpkg" if scored else None,
        },
        criteria={"area": {"mode": "hard_reject", "hard_min_area_km2": 0.001}},
    )
    dem_calls, calls = [], []

    result = build_generated_site_selection_from_toml(
        config_path=write_selection_toml(tmp_path, section, data=_data_dem()),
        dem_loader=dem_loader_spy(dem, dem_calls),
        flow_products_builder=flow_spy(correc=dem, acc=acc),
        delineation_builder=delineation_spy(calls, size=20.0),
        area_reader=lambda _path: 0.01,
    )

    assert dem_calls[0]["project_extent"] == (0.0, 0.0, 30.0, 30.0)
    assert len(calls) == 2
    assert [site.site_id for site in result.selection.selected] == [
        "network_00001",
        "network_00002",
    ]
    distance = result.candidates[0].attributes.get("reference_network_distance_m")
    assert distance == (20.0 if scored else None)
    paths = result.output_paths
    audit = [
        json.loads(line) for line in paths["candidate_generation_jsonl"].read_text().splitlines()
    ]
    assert [row["status"] for row in audit] == ["accepted", "accepted", "rejected"]
    assert audit[-1]["rejection_reason"] == "max_generated_candidates_reached"
    outlets = json.loads(paths["candidate_outlets_geojson"].read_text(encoding="utf-8"))
    assert outlets["hydromodpy_geometry_role"] == "candidate_outlets"
    assert len(outlets["features"]) == 2
    assert paths["generated_network_geojson"].is_file() and paths["selected_sites_csv"].is_file()
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["action"] == "generated_candidates"
    assert manifest["outputs"]["candidate_generation_jsonl"] == "candidate_generation.jsonl"
    assert ("reference_network" in manifest["flow_products"]) is scored


def test_the_dem_area_light_selection_writes_its_diagnostics(tmp_path):
    acc = np.ones((10, 10))
    acc[0, 0], acc[9, 9] = 100.0, 99.0
    acc_path = write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    dem = write_accumulation_raster(tmp_path / "dem.tif", np.ones((10, 10)), cell_size=1000.0)
    section = selection_section(
        input={"mode": "dem_area_light"},
        dem={"path": "dem.tif"},
        territory={
            "mode": "admin_departments",
            "regions": [],
            "departments": ["35"],
            "clip_to_territory": False,
        },
        hydrology={"network_threshold_area_km2": 1.0},
        dem_area_light={"n_basins": 1},
    )
    calls: list = []

    result = build_dem_area_light_site_selection_from_toml(
        config_path=write_selection_toml(tmp_path, section),
        flow_products_builder=flow_spy(correc=dem, acc=acc_path),
        raw_accumulation_builder=lambda **_kwargs: acc_path,
        delineation_builder=delineation_spy(calls, size=20.0),
        area_reader=lambda _path: 100.0,
    )

    assert len(result.candidates) == len(calls) == 2
    assert calls[0]["snap_dist"] == 1
    assert len(result.selection.selected) == 1
    diagnostics = pd.read_csv(result.output_paths["diagnostics_csv"]).set_index("metric")["count"]
    assert diagnostics.to_dict() == {
        "raw_candidates": 2,
        "thinned_candidates": 2,
        "delineated_basins": 2,
        "valid_basins": 2,
        "selected_basins": 1,
    }
    assert result.output_paths["candidate_outlets_geojson"].is_file()
    manifest = json.loads(
        result.output_paths["site_selection_manifest_json"].read_text(encoding="utf-8")
    )
    assert manifest["action"] == "dem_area_light"
