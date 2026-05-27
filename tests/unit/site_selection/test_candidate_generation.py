from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.generation import (
    accumulation_to_area_km2,
    candidate_generation_evidence_with_candidate_attributes,
    generate_dem_area_light_candidate_outlets,
    generate_network_candidate_outlets,
    write_candidate_generation_jsonl,
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    score_outlets_against_reference_network,
)
from hydromodpy.spatial.site_selection.config import (
    DemAreaLightConfig,
    HydrologyConfig,
    OutletsConfig,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts
from hydromodpy.workflow.site_selection import (
    build_dem_area_light_site_selection_from_toml,
    build_generated_site_selection_from_toml,
)
from tests.unit.site_selection._geojson import write_square_geojson


@pytest.mark.fast
def test_generate_network_candidate_outlets_samples_high_accumulation_cells(tmp_path):
    acc_path = _write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [90.0, 1.0, 1.0, 1.0, 1.0],
                [1.0, 1.0, 1.0, 1.0, 1.0],
                [1.0, 1.0, 50.0, 1.0, 1.0],
                [1.0, 1.0, 1.0, 1.0, 1.0],
                [1.0, 1.0, 1.0, 1.0, 100.0],
            ],
            dtype="float64",
        ),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    candidates, evidence = generate_network_candidate_outlets(
        flow_products=flow_products,
        outlets=OutletsConfig(
            min_distance_between_outlets_km=0.03,
            max_generated_candidates=2,
        ),
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "network_00001",
        "network_00002",
    ]
    assert candidates[0].x == pytest.approx(45.0)
    assert candidates[0].y == pytest.approx(5.0)
    assert candidates[0].priority == pytest.approx(100.0)
    assert candidates[1].x == pytest.approx(5.0)
    assert candidates[1].y == pytest.approx(45.0)
    assert evidence[0].raster_row == 4
    assert evidence[0].raster_col == 4

    jsonl_path = write_candidate_generation_jsonl(
        tmp_path / "candidate_generation.jsonl",
        evidence,
    )
    geojson_path = write_candidate_outlets_geojson(
        tmp_path / "candidate_outlets.geojson",
        candidates,
    )

    first_row = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert first_row["candidate_id"] == "network_00001"
    rejected_rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if '"status": "rejected"' in line
    ]
    assert {row["rejection_reason"] for row in rejected_rows} == {
        "max_generated_candidates_reached",
    }
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert geojson["hydromodpy_geometry_role"] == "candidate_outlets"
    assert len(geojson["features"]) == 2


@pytest.mark.fast
def test_accumulation_to_area_km2_uses_raw_cell_counts():
    areas = accumulation_to_area_km2(
        np.array([[1.0, 100.0], [75.0, 125.0]]),
        cell_area_m2=1_000_000.0,
    )

    assert areas.tolist() == [[1.0, 100.0], [75.0, 125.0]]


@pytest.mark.fast
def test_generate_dem_area_light_candidate_outlets_filters_area_and_spacing(tmp_path):
    acc = np.ones((10, 10), dtype="float64")
    acc[0, 0] = 100.0
    acc[0, 2] = 101.0
    acc[9, 9] = 99.0
    acc[5, 5] = 130.0
    acc[4, 4] = 74.0
    acc_path = _write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=1.0,
        compute_strahler=True,
    )

    candidates, evidence = generate_dem_area_light_candidate_outlets(
        flow_products=flow_products,
        dem_area_light=DemAreaLightConfig(
            target_area_km2=100.0,
            min_area_km2=75.0,
            max_area_km2=125.0,
            n_basins=2,
        ),
        hydrology=HydrologyConfig(network_threshold_area_km2=1.0),
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "dem_area_00001",
        "dem_area_00002",
    ]
    assert candidates[0].attributes["upstream_area_km2"] == pytest.approx(100.0)
    assert candidates[1].attributes["upstream_area_km2"] == pytest.approx(99.0)
    assert any(row.rejection_reason == "min_outlet_distance" for row in evidence)


@pytest.mark.fast
def test_generate_dem_area_light_candidate_outlets_honors_search_geometry(tmp_path):
    box = pytest.importorskip("shapely.geometry").box
    acc = np.ones((3, 3), dtype="float64")
    acc[0, 0] = 100.0
    acc[2, 2] = 99.0
    acc_path = _write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=1.0,
        compute_strahler=True,
    )

    candidates, evidence = generate_dem_area_light_candidate_outlets(
        flow_products=flow_products,
        dem_area_light=DemAreaLightConfig(
            target_area_km2=100.0,
            min_area_km2=75.0,
            max_area_km2=125.0,
            n_basins=1,
        ),
        hydrology=HydrologyConfig(network_threshold_area_km2=1.0),
        search_geometry=box(2000.0, 0.0, 3000.0, 1000.0),
    )

    assert [candidate.candidate_id for candidate in candidates] == ["dem_area_00001"]
    assert candidates[0].x == pytest.approx(2500.0)
    assert candidates[0].y == pytest.approx(500.0)
    assert evidence[0].evidence_json["raw_candidate_cells"] == 1


@pytest.mark.fast
def test_generated_candidates_workflow_writes_candidate_audit_outputs(tmp_path):
    acc_path = _write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [20.0, 1.0, 1.0],
                [1.0, 1.0, 1.0],
                [1.0, 1.0, 30.0],
            ],
            dtype="float64",
        ),
    )
    dem_path = _write_accumulation_raster(
        tmp_path / "dem.tif",
        np.ones((3, 3), dtype="float64"),
    )
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "generated_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "generated_candidates"',
                "",
                "[site_selection.dem]",
                'path = "dem.tif"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'primary_axes = ["area"]',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                'country = "FR"',
                "bbox = [0.0, 0.0, 30.0, 30.0]",
                "",
                "[site_selection.hydrology]",
                "network_threshold_area_km2 = 0.0001",
                "",
                "[site_selection.outlets]",
                "max_generated_candidates = 2",
                "min_distance_between_outlets_km = 0.01",
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 0.001",
                "hard_max_area_km2 = 1.0",
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_flow_builder(**_kwargs):
        return FlowProducts(correc=str(dem_path), direc="direc.tif", acc=str(acc_path))

    def fake_delineation_builder(**kwargs):
        calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        write_square_geojson(watershed, size=20.0)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    result = build_generated_site_selection_from_toml(
        config_path=config_path,
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 0.01,
    )

    assert len(result.candidates) == 2
    assert len(calls) == 2
    assert [catchment.site_id for catchment in result.selection.selected] == [
        "network_00001",
        "network_00002",
    ]
    assert result.output_paths["candidate_generation_jsonl"].is_file()
    assert result.output_paths["candidate_outlets_geojson"].is_file()
    assert result.output_paths["generated_network_geojson"].is_file()
    assert result.output_paths["selected_sites_csv"].is_file()
    manifest = json.loads(
        result.output_paths["site_selection_manifest_json"].read_text(encoding="utf-8")
    )
    assert manifest["action"] == "generated_candidates"
    assert manifest["outputs"]["candidate_generation_jsonl"] == "candidate_generation.jsonl"
    assert manifest["outputs"]["generated_network_geojson"] == "generated_dem_network.geojson"


@pytest.mark.fast
def test_dem_area_light_workflow_writes_outputs_and_diagnostics(tmp_path):
    acc = np.ones((10, 10), dtype="float64")
    acc[0, 0] = 100.0
    acc[9, 9] = 99.0
    acc_path = _write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    dem_path = _write_accumulation_raster(
        tmp_path / "dem.tif",
        np.ones((10, 10), dtype="float64"),
        cell_size=1000.0,
    )
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[site_selection]",
                'selection_id = "dem_area_demo"',
                'output_root = "out"',
                "",
                "[site_selection.input]",
                'mode = "dem_area_light"',
                "",
                "[site_selection.strategy]",
                'principle = "criteria_crossing"',
                'profile = "area_only"',
                'primary_axes = ["area"]',
                'observation_role = "report_only"',
                'geology_role = "report_only"',
                "",
                "[site_selection.criteria.area]",
                'mode = "hard_reject"',
                "hard_min_area_km2 = 75.0",
                "hard_max_area_km2 = 125.0",
                "",
                "[site_selection.dem]",
                'path = "dem.tif"',
                "",
                "[site_selection.territory]",
                'mode = "bbox"',
                'country = "FR"',
                "bbox = [0.0, 0.0, 10000.0, 10000.0]",
                "",
                "[site_selection.hydrology]",
                "network_threshold_area_km2 = 1.0",
                "",
                "[site_selection.dem_area_light]",
                "target_area_km2 = 100.0",
                "min_area_km2 = 75.0",
                "max_area_km2 = 125.0",
                "n_basins = 1",
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_flow_builder(**_kwargs):
        return FlowProducts(correc=str(dem_path), direc="direc.tif", acc=str(acc_path))

    def fake_delineation_builder(**kwargs):
        calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        watershed = output_dir / "watershed.geojson"
        write_square_geojson(watershed, size=20.0)
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(watershed),
        )

    result = build_dem_area_light_site_selection_from_toml(
        config_path=config_path,
        flow_products_builder=fake_flow_builder,
        raw_accumulation_builder=lambda **_kwargs: acc_path,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert len(result.candidates) == 2
    assert len(calls) == 2
    assert calls[0]["snap_dist"] == 1
    assert len(result.selection.selected) == 1
    assert result.output_paths["diagnostics_csv"].is_file()
    manifest = json.loads(
        result.output_paths["site_selection_manifest_json"].read_text(encoding="utf-8")
    )
    assert manifest["action"] == "dem_area_light"
    assert manifest["outputs"]["diagnostics_csv"] == "diagnostics.csv"


@pytest.mark.fast
def test_generated_network_geojson_exports_dem_stream_segments(tmp_path):
    acc_path = _write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [1.0, 1.0, 1.0],
                [1.0, 50.0, 60.0],
                [1.0, 1.0, 70.0],
            ],
            dtype="float64",
        ),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    path = write_generated_network_geojson(
        tmp_path / "generated_dem_network.geojson",
        flow_products=flow_products,
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["hydromodpy_geometry_role"] == "generated_dem_network"
    assert payload["hydromodpy_coordinate_crs"] == "EPSG:2154"
    assert any(
        feature["geometry"]["type"] == "LineString"
        for feature in payload["features"]
    )


@pytest.mark.fast
def test_generated_network_geojson_honors_search_geometry(tmp_path):
    box = pytest.importorskip("shapely.geometry").box
    acc_path = _write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array(
            [
                [90.0, 1.0, 1.0],
                [90.0, 1.0, 80.0],
                [90.0, 1.0, 80.0],
            ],
            dtype="float64",
        ),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    path = write_generated_network_geojson(
        tmp_path / "generated_dem_network.geojson",
        flow_products=flow_products,
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
        search_geometry=box(20.0, 0.0, 30.0, 20.0),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    coordinates = [
        point
        for feature in payload["features"]
        for point in _feature_points(feature["geometry"])
    ]
    assert coordinates
    assert all(x >= 20.0 for x, _y in coordinates)


@pytest.mark.fast
def test_reference_network_scores_generated_candidates_and_updates_audit(tmp_path):
    gpd = pytest.importorskip("geopandas")
    LineString = pytest.importorskip("shapely.geometry").LineString
    acc_path = _write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array([[1.0, 50.0, 60.0]], dtype="float64"),
    )
    flow_products = SiteSelectionFlowProducts(
        products=FlowProducts(correc="fill.tif", direc="direc.tif", acc=str(acc_path)),
        method="dem_only",
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )
    candidates, evidence = generate_network_candidate_outlets(
        flow_products=flow_products,
        outlets=OutletsConfig(max_generated_candidates=1),
        hydrology=HydrologyConfig(network_threshold_area_km2=0.0001),
    )
    network = gpd.GeoDataFrame(
        [{"id": "ref"}],
        geometry=[LineString([(0.0, 5.0), (30.0, 5.0)])],
        crs="EPSG:2154",
    )

    scored = score_outlets_against_reference_network(
        candidates,
        network,
        max_distance_m=100.0,
        source="bdtopage",
    )
    updated = candidate_generation_evidence_with_candidate_attributes(evidence, scored)

    assert scored[0].attributes["reference_network_source"] == "bdtopage"
    assert scored[0].attributes["reference_network_distance_m"] == pytest.approx(0.0)
    assert updated[0].reference_network_status == "within_reference_network_tolerance"


def _write_accumulation_raster(
    path: Path,
    values: np.ndarray,
    *,
    cell_size: float = 10.0,
) -> Path:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float64",
        crs="EPSG:2154",
        transform=from_origin(0.0, float(values.shape[0]) * cell_size, cell_size, cell_size),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return path


def _feature_points(geometry: dict) -> list[list[float]]:
    if geometry["type"] == "Point":
        return [geometry["coordinates"]]
    if geometry["type"] == "LineString":
        return list(geometry["coordinates"])
    return []
