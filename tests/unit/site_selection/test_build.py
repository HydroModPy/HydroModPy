from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.build import (
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.workflow.site_selection import (
    build_observed_site_selection_from_toml,
    build_site_selection_from_hydrometry_config,
)


def _record(station_id: str, *, x: float = 350000.0, y: float = 6810000.0) -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01", "2020-01-02"], "value": [1.0, 2.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 2),
        location=StationLocation(
            id=station_id,
            x=x,
            y=y,
            crs="EPSG:2154",
            metadata={"station_name": f"Station {station_id}"},
        ),
    )


def _wgs84_hubeau_record(station_id: str) -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01", "2020-01-02"], "value": [1.0, 2.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 2),
        location=StationLocation(
            id=station_id,
            x=-1.65,
            y=48.12,
            crs="EPSG:4326",
            metadata={
                "station_name": f"Station {station_id}",
                "x_l93": "352000.0",
                "y_l93": "6812000.0",
            },
        ),
    )


def _config(tmp_path: Path) -> SiteSelectionConfig:
    return SiteSelectionConfig.model_validate(
        {
            "selection_id": "observed_demo",
            "output_root": tmp_path / "out",
            "strategy": {
                "principle": "observation_led",
                "primary_observation_type": "flow_station",
                "candidate_mode": "station_outlets",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
            "dem": {
                "source": "custom",
                "path": tmp_path / "dem.tif",
            },
            "outlets": {
                "candidate_mode": "station_outlets",
                "snap_dist_m": 150,
            },
        }
    )


@pytest.mark.fast
def test_build_site_selection_from_point_records_chains_candidates_delineation_selection_and_exports(
    tmp_path,
):
    flow_calls = {}
    delineation_calls = []

    def fake_flow_builder(**kwargs):
        flow_calls.update(kwargs)
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        delineation_calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_point_records(
        config=_config(tmp_path),
        point_records=[_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert flow_calls["dem_correc_type"] == "fill"
    assert delineation_calls[0]["snap_dist"] == 150
    assert [candidate.source_feature_id for candidate in result.candidates] == ["J123456701"]
    assert [catchment.site_id for catchment in result.selection.selected] == ["station_J123456701"]
    assert result.output_paths["selected_sites_csv"].is_file()
    assert result.output_paths["observation_evidence_jsonl"].is_file()
    assert result.output_paths["observation_points_geojson"].is_file()
    assert result.observation_evidence[0].feature_id == "J123456701"


@pytest.mark.fast
def test_build_site_selection_from_point_records_reprojects_station_locations(tmp_path):
    delineation_calls = []

    def fake_flow_builder(**kwargs):
        assert kwargs["crs_project"] == "EPSG:2154"
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        delineation_calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_point_records(
        config=_config(tmp_path),
        point_records=[_wgs84_hubeau_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert result.candidates[0].x == pytest.approx(352000.0)
    assert result.candidates[0].y == pytest.approx(6812000.0)
    assert result.candidates[0].crs == "EPSG:2154"
    assert delineation_calls[0]["x_outlet"] == pytest.approx(352000.0)
    assert delineation_calls[0]["y_outlet"] == pytest.approx(6812000.0)


@pytest.mark.fast
def test_build_site_selection_from_point_records_requires_dem(tmp_path):
    cfg = _config(tmp_path).model_copy(update={"dem": _config(tmp_path).dem.model_copy(update={"path": None})})

    with pytest.raises(ValueError, match="requires dem_init_path or dem.path"):
        build_site_selection_from_point_records(
            config=cfg,
            point_records=[_record("J123456701")],
            flow_products_builder=lambda **_kwargs: FlowProducts(
                correc="fill.tif",
                direc="direc.tif",
                acc="acc.tif",
            ),
        )


@pytest.mark.fast
def test_build_site_selection_from_hydrometry_config_uses_loader_then_builds(tmp_path):
    hydrometry_cfg = HydrometryConfig(
        date_start="2020-01-01",
        date_end="2020-01-02",
        sources=[HydrometrySourceConfig(source="hubeau", product="QmnJ")],
    )
    loader_calls = {}

    def fake_loader(**kwargs):
        loader_calls.update(kwargs)
        return [_record("J123456701")]

    def fake_flow_builder(**_kwargs):
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_hydrometry_config(
        config=_config(tmp_path),
        hydrometry_config=hydrometry_cfg,
        hydrometry_loader=fake_loader,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert loader_calls["config"] is hydrometry_cfg
    assert [candidate.source_feature_id for candidate in result.candidates] == ["J123456701"]
    assert result.output_paths == {}


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
        return [_wgs84_hubeau_record("J123456701")]

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
    assert calls["flow_dem"] == dem
    lon_min, lat_min, lon_max, lat_max = calls["hydrometry_extent"]
    assert -3.5 < lon_min < lon_max < -2.0
    assert 47.5 < lat_min < lat_max < 49.0
    assert result.candidates[0].crs == "EPSG:2154"
