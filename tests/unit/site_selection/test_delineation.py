from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.delineation import (
    delineate_candidate_outlet,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.delineation_pipeline import (
    delineate_site_selection_candidates,
)


@pytest.mark.fast
def test_delineate_candidate_outlet_delegates_to_existing_point_extractor(tmp_path):
    calls = {}

    def fake_builder(**kwargs):
        calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    outlet = CandidateOutlet(
        candidate_id="station_A",
        x=350000.0,
        y=6810000.0,
        crs="EPSG:2154",
        source="station",
    )
    flow_products = FlowProducts(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")

    result = delineate_candidate_outlet(
        outlet=outlet,
        flow_products=flow_products,
        output_root=tmp_path,
        snap_dist_m=250,
        builder=fake_builder,
        area_reader=lambda _path: 123.4,
    )

    assert calls["x_outlet"] == pytest.approx(350000.0)
    assert calls["y_outlet"] == pytest.approx(6810000.0)
    assert calls["snap_dist"] == 250
    assert calls["acc_path"] == "dem_acc.tif"
    assert calls["direc_path"] == "dem_direc.tif"
    assert calls["crs_project"] == "EPSG:2154"
    assert result.area_km2 == pytest.approx(123.4)
    assert result.status == "delineated"


@pytest.mark.fast
def test_delineate_candidate_outlet_can_snap_to_reference_network_before_dem(tmp_path):
    calls = {}

    def fake_builder(**kwargs):
        calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    outlet = CandidateOutlet(
        candidate_id="station_A",
        x=350010.0,
        y=6810025.0,
        crs="EPSG:2154",
        source="station_outlets",
    )
    reference_network = gpd.GeoDataFrame(
        geometry=[LineString([(350000.0, 6810000.0), (350100.0, 6810000.0)])],
        crs="EPSG:2154",
    )
    flow_products = FlowProducts(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")

    result = delineate_candidate_outlet(
        outlet=outlet,
        flow_products=flow_products,
        output_root=tmp_path,
        snap_dist_m=150,
        builder=fake_builder,
        area_reader=lambda _path: 123.4,
        reference_network=reference_network,
        reference_network_source="bdtopage",
        reference_network_max_distance_m=100.0,
    )

    assert calls["x_outlet"] == pytest.approx(350010.0)
    assert calls["y_outlet"] == pytest.approx(6810000.0)
    assert calls["snap_dist"] == 150
    assert result.outlet.attributes["reference_network_source"] == "bdtopage"
    assert result.outlet.attributes["reference_network_snap_distance_m"] == pytest.approx(25.0)


@pytest.mark.fast
def test_try_delineate_candidate_outlet_returns_rejected_record_on_failure(tmp_path):
    def failing_builder(**_kwargs):
        raise RuntimeError("snap failed")

    outlet = CandidateOutlet(
        candidate_id="station_A",
        x=350000.0,
        y=6810000.0,
        crs="EPSG:2154",
        source="station",
    )
    flow_products = FlowProducts(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")

    result = try_delineate_candidate_outlet(
        outlet=outlet,
        flow_products=flow_products,
        output_root=tmp_path,
        snap_dist_m=250,
        builder=failing_builder,
    )

    assert result.status == "rejected_delineation_failed"
    assert "snap failed" in result.failure_reason
    assert result.to_record()["candidate_id"] == "station_A"


@pytest.mark.fast
def test_delineate_site_selection_candidates_batches_candidates(tmp_path):
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    candidates = [
        CandidateOutlet("station_A", 350000.0, 6810000.0, "EPSG:2154", "station"),
        CandidateOutlet("station_B", 351000.0, 6811000.0, "EPSG:2154", "station"),
    ]
    flow_products = FlowProducts(correc="dem_fill.tif", direc="dem_direc.tif", acc="dem_acc.tif")

    results = delineate_site_selection_candidates(
        candidates,
        flow_products=flow_products,
        output_root=tmp_path,
        snap_dist_m=250,
        crs_project="EPSG:2154",
        delineation_builder=fake_builder,
        area_reader=lambda _path: 42.0,
    )

    assert [result.site_id for result in results] == ["station_A", "station_B"]
    assert [result.area_km2 for result in results] == [42.0, 42.0]
    assert [call["x_outlet"] for call in calls] == [350000.0, 351000.0]
    assert all(call["snap_dist"] == 250 for call in calls)
