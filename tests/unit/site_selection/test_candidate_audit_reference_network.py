from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.candidates.candidate_builders import (
    build_network_candidate_outlets,
    candidate_audit_evidence_with_candidate_attributes,
)
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    score_outlets_against_reference_network,
)
from hydromodpy.spatial.site_selection.config import (
    HydrologyConfig,
    OutletsConfig,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

from ._test_candidate_audit_builders import write_accumulation_raster


@pytest.mark.fast
def test_reference_network_scores_dem_network_candidates_and_updates_audit(tmp_path):
    gpd = pytest.importorskip("geopandas")
    LineString = pytest.importorskip("shapely.geometry").LineString
    acc_path = write_accumulation_raster(
        tmp_path / "acc.tif",
        np.array([[1.0, 50.0, 60.0]], dtype="float64"),
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
        outlets=OutletsConfig(max_network_candidates=1),
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
    updated = candidate_audit_evidence_with_candidate_attributes(evidence, scored)

    assert scored[0].attributes["reference_network_source"] == "bdtopage"
    assert scored[0].attributes["reference_network_distance_m"] == pytest.approx(0.0)
    assert updated[0].reference_network_status == "within_reference_network_tolerance"
