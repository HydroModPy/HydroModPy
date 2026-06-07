from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.generation import (
    generate_dem_area_light_candidate_outlets,
)
from hydromodpy.spatial.site_selection.config import (
    DemAreaLightConfig,
    HydrologyConfig,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

from ._test_candidate_generation_builders import write_accumulation_raster


@pytest.mark.fast
def test_generate_dem_area_light_candidate_outlets_filters_area_and_spacing(tmp_path):
    acc = np.ones((10, 10), dtype="float64")
    acc[0, 0] = 100.0
    acc[0, 2] = 101.0
    acc[9, 9] = 99.0
    acc[5, 5] = 130.0
    acc[4, 4] = 74.0
    acc_path = write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
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
    acc_path = write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
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
