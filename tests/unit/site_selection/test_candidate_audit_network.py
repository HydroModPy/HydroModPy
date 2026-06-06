from __future__ import annotations

import json

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.candidate_builders import (
    accumulation_to_area_km2,
    build_network_candidate_outlets,
    write_candidate_audit_jsonl,
    write_candidate_outlets_geojson,
)
from hydromodpy.spatial.site_selection.config import (
    HydrologyConfig,
    OutletsConfig,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

from ._test_candidate_audit_builders import write_accumulation_raster


@pytest.mark.fast
def test_build_network_candidate_outlets_samples_high_accumulation_cells(tmp_path):
    acc_path = write_accumulation_raster(
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
        flow_algorithm="d8",
        dem_correction_type="fill",
        network_threshold_area_km2=0.0001,
        compute_strahler=True,
    )

    candidates, evidence = build_network_candidate_outlets(
        flow_products=flow_products,
        outlets=OutletsConfig(
            min_distance_between_outlets_km=0.03,
            max_network_candidates=2,
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

    jsonl_path = write_candidate_audit_jsonl(
        tmp_path / "candidate_audit.jsonl",
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
        "max_network_candidates_reached",
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
