from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.workflow.site_selection import (
    build_dem_area_light_site_selection_from_toml,
    build_generated_site_selection_from_toml,
)

from ._geojson import write_square_geojson
from ._test_candidate_generation_builders import write_accumulation_raster


@pytest.mark.fast
def test_generated_candidates_workflow_writes_candidate_audit_outputs(tmp_path):
    acc_path = write_accumulation_raster(
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
    dem_path = write_accumulation_raster(
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
    acc_path = write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    dem_path = write_accumulation_raster(
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
