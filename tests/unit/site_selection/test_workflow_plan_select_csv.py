from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.workflow.site_selection import (
    load_data_dem_config_for_site_selection,
    select_delineated_catchments_from_csv,
)

from ._test_workflow_plan_builders import (
    make_fake_delineation_builder,
    make_fake_flow_builder,
)


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
                "[report.html]",
                'profile = "site_selection"',
                "build_at_end = true",
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

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        flow_products_builder=make_fake_flow_builder(),
        delineation_builder=make_fake_delineation_builder(),
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
                "dem_snap_max_distance_m = 150",
                'reference_network_source = "custom"',
                'reference_network_path = "reference_network.gpkg"',
                "reference_network_snap_max_distance_m = 50.0",
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

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        flow_products_builder=make_fake_flow_builder(),
        delineation_builder=make_fake_delineation_builder(calls),
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
                "delineation_buffer_km = 2.0",
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

    result, paths = select_delineated_catchments_from_csv(
        config_path=config_path,
        catchments_csv=catchments_csv,
        dem_loader=fake_dem_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=make_fake_delineation_builder(),
        area_reader=lambda _path: 100.0,
    )

    assert [catchment.site_id for catchment in result.selected] == ["site_001"]
    manifest = json.loads(paths["site_selection_manifest_json"].read_text(encoding="utf-8"))
    assert manifest["flow_products"]["dem_path"] == str(dem)
