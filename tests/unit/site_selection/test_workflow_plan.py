from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.workflow.site_selection import (
    load_data_dem_config_for_site_selection,
    load_delineated_catchments_csv,
    load_hydrometry_config_for_site_selection,
    plan_site_selection,
    run_site_selection_workflow,
    select_delineated_catchments_from_csv,
)


@pytest.mark.fast
def test_plan_site_selection_loads_toml_and_resolves_paths(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "area_only_demo"',
                'output_root = "outputs/site_selection/area_only_demo"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Auvergne-Rhone-Alpes"]',
                "",
                "[site_selection.criteria]",
                'ruleset = "france_area_only_v1"',
                'hard_reject = ["dem_coverage", "geometry_validity", "area_range"]',
                'report_only = ["geology", "hydrometry", "piezometry"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "target_area_km2 = 100.0",
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_site_selection(config_path)

    assert plan.config.output_root == tmp_path / "outputs/site_selection/area_only_demo"
    assert plan.manifest["selection_id"] == "area_only_demo"
    assert plan.manifest["strategy"]["profile"] == "area_only"
    assert plan.manifest["criteria"]["area_mode"] == "hard_reject"
    assert "selected" in plan.manifest["planned_outputs"]
    assert "regional_lab_csv" in plan.manifest["planned_outputs"]
    assert "geoparquet" not in plan.manifest["planned_outputs"]
    assert "report_md" not in plan.manifest["planned_outputs"]
    assert "report_html" not in plan.manifest["planned_outputs"]


@pytest.mark.fast
def test_site_selection_plan_can_write_manifest(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "observed_demo"',
                'output_root = "out"',
                "",
                "[site_selection.strategy]",
                'principle = "observation_led"',
                'primary_observation_type = "flow_station"',
                'candidate_mode = "station_outlets"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_site_selection(config_path)
    manifest_path = plan.write_manifest()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["selection_id"] == "observed_demo"
    assert payload["strategy"]["candidate_mode"] == "station_outlets"


@pytest.mark.fast
def test_load_delineated_catchments_csv(tmp_path):
    vectors = tmp_path / "vectors"
    vectors.mkdir()
    watershed = vectors / "site_001.geojson"
    watershed.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x_outlet,y_outlet,outlet_crs,area_km2,status,watershed_shp",
                "site_001,350000,6810000,EPSG:2154,100,delineated,vectors/site_001.geojson",
            ]
        ),
        encoding="utf-8",
    )

    catchments = load_delineated_catchments_csv(catchments_csv)

    assert len(catchments) == 1
    assert catchments[0].site_id == "site_001"
    assert catchments[0].outlet.x == pytest.approx(350000.0)
    assert catchments[0].area_km2 == pytest.approx(100.0)
    assert catchments[0].watershed_shp == str(watershed.resolve())


@pytest.mark.fast
def test_load_hydrometry_config_for_site_selection_resolves_custom_paths(tmp_path):
    data_dir = tmp_path / "hydrometry_data"
    data_dir.mkdir()
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[hydrometry]",
                'date_start = "2020-01-01"',
                'date_end = "2020-01-02"',
                "",
                "[[hydrometry.sources]]",
                'source = "custom"',
                'path = "hydrometry_data"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_hydrometry_config_for_site_selection(config_path)

    assert cfg.sources[0].path == data_dir.resolve()


@pytest.mark.fast
def test_select_delineated_catchments_from_csv_writes_outputs(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "area_only_demo"',
                'output_root = "out"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Auvergne-Rhone-Alpes"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x,y,area_km2",
                "site_ok,0,0,100",
                "site_bad,1,1,50",
            ]
        ),
        encoding="utf-8",
    )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        output_root=tmp_path / "selected_out",
        region_id="AURA",
    )

    assert [catchment.site_id for catchment in result.selected] == ["site_ok"]
    with paths["selected_sites_csv"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["region_id"] == "AURA"
    assert rows[0]["site_id"] == "site_ok"


@pytest.mark.fast
def test_select_delineated_catchments_from_csv_can_delineate_from_outlets(tmp_path):
    dem = tmp_path / "dem.tif"
    dem.write_text("synthetic dem placeholder", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "from_outlet_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                "delineate_from_outlets = true",
                "",
                "[site_selection.dem]",
                'path = "dem.tif"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_001,10,20,100\n", encoding="utf-8")

    def fake_flow_builder(**kwargs):
        output_dir = Path(kwargs["dem_out_dir_path"])
        return FlowProducts(
            correc=str(output_dir / "fill.tif"),
            direc=str(output_dir / "direc.tif"),
            acc=str(output_dir / "acc.tif"),
        )

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        _write_square_geojson(watershed)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert [catchment.watershed_shp for catchment in result.selected]
    basins = json.loads(paths["selected_basins_geojson"].read_text(encoding="utf-8"))
    assert basins["features"][0]["properties"]["watershed_shp"].endswith("watershed.geojson")


@pytest.mark.fast
def test_select_delineated_catchments_from_csv_can_use_custom_reference_network(tmp_path):
    import geopandas as gpd
    from shapely.geometry import LineString

    dem = tmp_path / "dem.tif"
    dem.write_text("synthetic dem placeholder", encoding="utf-8")
    reference_network = tmp_path / "reference_network.gpkg"
    gpd.GeoDataFrame(
        geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        crs="EPSG:2154",
    ).to_file(reference_network, driver="GPKG")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "from_outlet_reference_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                "delineate_from_outlets = true",
                "",
                "[site_selection.dem]",
                'path = "dem.tif"',
                "",
                "[site_selection.outlets]",
                'snap_strategy = "bdtopage_then_dem"',
                "snap_dist_m = 150",
                'reference_network_source = "custom"',
                'reference_network_path = "reference_network.gpkg"',
                "reference_network_max_distance_m = 50.0",
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                "bbox = [0.0, 0.0, 100.0, 100.0]",
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_001,25,12,100\n", encoding="utf-8")
    calls = {}

    def fake_flow_builder(**kwargs):
        output_dir = Path(kwargs["dem_out_dir_path"])
        return FlowProducts(
            correc=str(output_dir / "fill.tif"),
            direc=str(output_dir / "direc.tif"),
            acc=str(output_dir / "acc.tif"),
        )

    def fake_delineation_builder(**kwargs):
        calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        _write_square_geojson(watershed)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert calls["x_outlet"] == pytest.approx(25.0)
    assert calls["y_outlet"] == pytest.approx(0.0)
    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["outlets"]["snap_strategy"] == "bdtopage_then_dem"
    assert manifest["flow_products"]["reference_network"]["source"] == "custom"


@pytest.mark.fast
def test_select_delineated_catchments_from_csv_can_resolve_dem_from_data_section(tmp_path):
    dem = tmp_path / "data" / "dem" / "real_dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_text("real dem placeholder", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "data_dem_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                "delineate_from_outlets = true",
                "",
                "[site_selection.dem]",
                'source = "data"',
                "margin_km = 2.0",
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                "bbox = [0.0, 0.0, 10000.0, 10000.0]",
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[data]",
                'types = ["dem"]',
                "",
                "[[data.dem.sources]]",
                'source = "custom"',
                'path = "data/dem/real_dem.tif"',
            ]
        ),
        encoding="utf-8",
    )
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_001,10,20,100\n", encoding="utf-8")

    dem_config = load_data_dem_config_for_site_selection(config_path)
    assert dem_config is not None
    assert dem_config.sources[0].path == dem

    def fake_dem_loader(**kwargs):
        assert kwargs["project_extent"] == (-2000.0, -2000.0, 12000.0, 12000.0)
        return [
            FieldRecord(
                variable="dem",
                source="custom",
                unit="m",
                data=dem,
                bbox=kwargs["project_extent"],
                crs="EPSG:2154",
            )
        ]

    def fake_flow_builder(**kwargs):
        assert Path(kwargs["dem_init_path"]) == dem
        output_dir = Path(kwargs["dem_out_dir_path"])
        return FlowProducts(
            correc=str(output_dir / "fill.tif"),
            direc=str(output_dir / "direc.tif"),
            acc=str(output_dir / "acc.tif"),
        )

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        _write_square_geojson(watershed)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        dem_loader=fake_dem_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["flow_products"]["dem_path"] == str(dem)


@pytest.mark.fast
def test_run_site_selection_workflow_plan_mode_writes_manifest(tmp_path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "plan_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "plan_only"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "plan"
    assert summary["selection_id"] == "plan_demo"
    assert (tmp_path / "out" / "site_selection_plan.json").is_file()
    assert summary["site_selection_report_html"]
    assert (tmp_path / "out" / "review" / "index.html").is_file()
    html = (tmp_path / "out" / "review" / "index.html").read_text(encoding="utf-8")
    assert "Rapport HTML de plan" in html
    assert "Aucun site n'est retenu ou rejete" in html


@pytest.mark.fast
def test_run_site_selection_workflow_uses_predelineated_catchments(tmp_path):
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text(
        "\n".join(
            [
                "site_id,x,y,area_km2",
                "site_ok,0,0,100",
                "site_bad,1,1,50",
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "select_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "delineated_catchments"',
                'catchments_csv = "catchments.csv"',
                'region_id = "AURA"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Auvergne-Rhone-Alpes"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.output]",
                "write_report_html = true",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["action"] == "delineated_catchments"
    assert summary["selected"] == 1
    assert summary["rejected"] == 1
    assert (tmp_path / "out" / "selected_sites.csv").is_file()
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()
    assert (tmp_path / "out" / "review" / "index.html").is_file()


@pytest.mark.fast
def test_run_site_selection_workflow_writes_manifest_without_html_by_default(tmp_path):
    catchments_csv = tmp_path / "catchments.csv"
    catchments_csv.write_text("site_id,x,y,area_km2\nsite_ok,0,0,100\n", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "manifest_only_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "delineated_catchments"',
                'catchments_csv = "catchments.csv"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.territory]",
                'mode = "admin_regions"',
                'country = "FR"',
                'regions = ["Bretagne"]',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_site_selection_workflow(config_path)

    assert summary["selected"] == 1
    assert (tmp_path / "out" / "site_selection_manifest.json").is_file()
    assert not (tmp_path / "out" / "review" / "index.html").exists()
    assert summary["site_selection_report_html"] == ""


def _write_square_geojson(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
