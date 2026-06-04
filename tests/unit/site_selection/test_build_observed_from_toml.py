from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.workflow.site_selection import build_observed_site_selection_from_toml

from ._test_build_builders import make_wgs84_hubeau_record


@pytest.mark.fast
def test_build_observed_site_selection_from_toml_resolves_dem_and_observation_extent(tmp_path):
    dem = tmp_path / "data" / "dem.tif"
    dem.parent.mkdir()
    dem.write_text("fake dem", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "observed_data_dem"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "hydrometry"',
                "",
                "[site_selection.dem]",
                'source = "data"',
                "",
                "[site_selection.strategy]",
                'principle = "observation_led"',
                'profile = "gauged_downstream_station"',
                'primary_observation_type = "flow_station"',
                'candidate_mode = "station_outlets"',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                'country = "FR"',
                "bbox = [300000.0, 6800000.0, 310000.0, 6810000.0]",
                "",
                "[hydrometry]",
                'date_start = "2020-01-01"',
                'date_end = "2020-01-02"',
                "",
                "[[hydrometry.sources]]",
                'source = "hubeau"',
                'product = "QmnJ"',
                "",
                "[data]",
                'types = ["dem"]',
                "",
                "[[data.dem.sources]]",
                'source = "custom"',
                'path = "data/dem.tif"',
            ]
        ),
        encoding="utf-8",
    )
    calls = {}

    def fake_dem_loader(**kwargs):
        calls["dem_extent"] = kwargs["project_extent"]
        calls["dem_data_root"] = kwargs["data_root"]
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

    def fake_hydrometry_loader(**kwargs):
        calls["hydrometry_extent"] = kwargs["project_extent"]
        calls["hydrometry_data_root"] = kwargs["data_root"]
        return [make_wgs84_hubeau_record("J123456701")]

    def fake_flow_builder(**kwargs):
        calls["flow_dem"] = Path(kwargs["dem_init_path"])
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_observed_site_selection_from_toml(
        config_path=config_path,
        dem_loader=fake_dem_loader,
        hydrometry_loader=fake_hydrometry_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert calls["dem_extent"] == (300000.0, 6800000.0, 310000.0, 6810000.0)
    assert calls["dem_data_root"] == tmp_path / "out" / "data"
    assert calls["hydrometry_data_root"] == tmp_path / "out" / "data"
    assert calls["flow_dem"] == dem
    lon_min, lat_min, lon_max, lat_max = calls["hydrometry_extent"]
    assert -3.5 < lon_min < lon_max < -2.0
    assert 47.5 < lat_min < lat_max < 49.0
    assert result.candidates[0].crs == "EPSG:2154"


@pytest.mark.fast
def test_build_observed_site_selection_from_toml_uses_station_extent_for_dem(tmp_path):
    dem = tmp_path / "data" / "dem.tif"
    dem.parent.mkdir()
    dem.write_text("fake dem", encoding="utf-8")
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "observed_data_dem"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "hydrometry"',
                "",
                "[site_selection.dem]",
                'source = "data"',
                'request_extent = "outlets"',
                "margin_km = 2.0",
                "",
                "[site_selection.strategy]",
                'principle = "observation_led"',
                'profile = "gauged_downstream_station"',
                'primary_observation_type = "flow_station"',
                'candidate_mode = "station_outlets"',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                'country = "FR"',
                "bbox = [300000.0, 6800000.0, 310000.0, 6810000.0]",
                "",
                "[hydrometry]",
                'date_start = "2020-01-01"',
                'date_end = "2020-01-02"',
                "",
                "[[hydrometry.sources]]",
                'source = "hubeau"',
                'product = "QmnJ"',
                "",
                "[data]",
                'types = ["dem"]',
                "",
                "[[data.dem.sources]]",
                'source = "custom"',
                'path = "data/dem.tif"',
            ]
        ),
        encoding="utf-8",
    )
    calls = {"order": []}
    progress_messages: list[str] = []

    def fake_dem_loader(**kwargs):
        calls["order"].append("dem")
        calls["dem_extent"] = kwargs["project_extent"]
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

    def fake_hydrometry_loader(**kwargs):
        calls["order"].append("hydrometry")
        calls["hydrometry_extent"] = kwargs["project_extent"]
        return [make_wgs84_hubeau_record("J123456701")]

    def fake_flow_builder(**kwargs):
        calls["flow_dem"] = Path(kwargs["dem_init_path"])
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_observed_site_selection_from_toml(
        config_path=config_path,
        dem_loader=fake_dem_loader,
        hydrometry_loader=fake_hydrometry_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
        progress_callback=progress_messages.append,
    )

    assert calls["order"] == ["hydrometry", "dem"]
    assert calls["dem_extent"] == pytest.approx((350000.0, 6810000.0, 354000.0, 6814000.0))
    lon_min, lat_min, lon_max, lat_max = calls["hydrometry_extent"]
    assert -3.5 < lon_min < lon_max < -2.0
    assert 47.5 < lat_min < lat_max < 49.0
    assert calls["flow_dem"] == dem
    assert result.candidates[0].x == pytest.approx(352000.0)
    assert result.candidates[0].y == pytest.approx(6812000.0)
    assert any("loading hydrometry records" in message for message in progress_messages)
    assert any("DEM extent from 1 station outlets" in message for message in progress_messages)
    assert any("finished with 1 candidates" in message for message in progress_messages)
