from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.site_selection.candidates.generation import (
    accumulation_to_area_km2,
    candidate_generation_evidence_with_candidate_attributes,
    ensure_raw_accumulation_cells,
    generate_dem_area_light_candidate_outlets,
    generate_network_candidate_outlets,
)
from hydromodpy.spatial.site_selection.config.dem_config import DemAreaLightConfig, HydrologyConfig
from hydromodpy.spatial.site_selection.config.outlets_config import OutletsConfig
from hydromodpy.spatial.site_selection.hydrology.reference_network import (
    score_outlets_against_reference_network,
)
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.site_selection_cases import site_flow_products, write_accumulation_raster

pytestmark = pytest.mark.fast

NETWORK = np.ones((5, 5))
NETWORK[0, 0], NETWORK[2, 2], NETWORK[4, 4], NETWORK[4, 3] = 90.0, 50.0, 100.0, 95.0
HYDROLOGY = HydrologyConfig(network_threshold_area_km2=0.0001)


def _network(tmp_path, values=NETWORK, search_geometry=None, **outlets):
    flow_products = site_flow_products(write_accumulation_raster(tmp_path / "acc.tif", values))
    return generate_network_candidate_outlets(
        flow_products=flow_products,
        outlets=OutletsConfig(**outlets),
        hydrology=HYDROLOGY,
        search_geometry=search_geometry,
    )


def test_the_network_sampling_keeps_the_largest_accumulations_apart(tmp_path):
    candidates, evidence = _network(
        tmp_path, min_distance_between_outlets_km=0.03, max_generated_candidates=2
    )

    assert [one.candidate_id for one in candidates] == ["network_00001", "network_00002"]
    assert [(one.x, one.y, one.priority) for one in candidates] == [
        (45.0, 5.0, 100.0),
        (5.0, 45.0, 90.0),
    ]
    assert (evidence[0].raster_row, evidence[0].raster_col) == (4, 4)
    reasons = [row.rejection_reason for row in evidence if row.status == "rejected"]
    assert reasons == ["min_distance_between_outlets", "max_generated_candidates_reached"]
    _, unaudited = _network(
        tmp_path,
        min_distance_between_outlets_km=0.03,
        max_generated_candidates=2,
        max_rejected_candidate_audit_records=1,
    )
    assert [row.rejection_reason for row in unaudited if row.status == "rejected"] == [
        "min_distance_between_outlets"
    ]


def test_a_search_geometry_without_a_network_cell_falls_back_to_its_cells(tmp_path):
    candidates, _ = _network(
        tmp_path, max_generated_candidates=1, search_geometry=box(20.0, 0.0, 30.0, 10.0)
    )

    assert [(one.x, one.y, one.priority) for one in candidates] == [(25.0, 5.0, 1.0)]


def test_an_empty_search_geometry_gives_no_candidate(tmp_path):
    assert _network(tmp_path, search_geometry=Polygon()) == ([], [])


def test_the_reference_network_scores_generated_candidates_and_updates_the_audit(tmp_path):
    gpd = pytest.importorskip("geopandas")
    candidates, evidence = _network(tmp_path, np.array([[1.0, 50.0, 60.0]]))
    network = gpd.GeoDataFrame(geometry=[LineString([(0.0, 5.0), (30.0, 5.0)])], crs="EPSG:2154")

    scored = score_outlets_against_reference_network(
        candidates, network, max_distance_m=100.0, source="bdtopage"
    )
    updated = candidate_generation_evidence_with_candidate_attributes(evidence, scored)

    assert scored[0].attributes["reference_network_source"] == "bdtopage"
    assert scored[0].attributes["reference_network_distance_m"] == 0.0
    assert updated[0].reference_network_status == "within_reference_network_tolerance"


def _dem_area(tmp_path, acc, *, n_basins=2, **kwargs):
    acc_path = write_accumulation_raster(tmp_path / "acc_cells.tif", acc, cell_size=1000.0)
    return generate_dem_area_light_candidate_outlets(
        flow_products=site_flow_products(acc_path, threshold_km2=1.0),
        dem_area_light=DemAreaLightConfig(n_basins=n_basins),
        hydrology=HydrologyConfig(network_threshold_area_km2=1.0),
        **kwargs,
    )


def test_the_dem_area_candidates_keep_the_window_and_their_spacing(tmp_path):
    acc = np.ones((10, 10))
    acc[0, 0], acc[0, 2], acc[9, 9], acc[5, 5], acc[4, 4] = 100.0, 101.0, 99.0, 130.0, 74.0

    candidates, evidence = _dem_area(tmp_path, acc)

    assert [one.candidate_id for one in candidates] == ["dem_area_00001", "dem_area_00002"]
    assert [one.attributes["upstream_area_km2"] for one in candidates] == [100.0, 99.0]
    assert any(row.rejection_reason == "min_outlet_distance" for row in evidence)


def test_the_dem_area_candidates_stop_at_the_delineation_budget(tmp_path):
    acc = np.ones((10, 10))
    acc[0, 0], acc[9, 9] = 100.0, 99.0

    candidates, evidence = _dem_area(tmp_path, acc, max_candidates_before_delineation=1)

    assert len(candidates) == 1
    assert evidence[-1].rejection_reason == "max_candidates_before_delineation_reached"


def test_the_dem_area_candidates_honor_the_search_geometry(tmp_path):
    acc = np.ones((3, 3))
    acc[0, 0], acc[2, 2] = 100.0, 99.0

    candidates, evidence = _dem_area(
        tmp_path, acc, n_basins=1, search_geometry=box(2000.0, 0.0, 3000.0, 1000.0)
    )

    assert [(one.candidate_id, one.x, one.y) for one in candidates] == [
        ("dem_area_00001", 2500.0, 500.0)
    ]
    assert evidence[0].evidence_json["raw_candidate_cells"] == 1


def test_a_log_scaled_accumulation_is_refused_by_the_dem_area_scan(tmp_path):
    with pytest.raises(ValueError, match="looks log-scaled"):
        _dem_area(tmp_path, np.full((3, 3), 4.6))


@pytest.mark.xfail(
    strict=True,
    reason="looks_log_scaled reads any raster whose largest count is under 100 as log scaled",
)
def test_a_small_raw_accumulation_is_read_as_cell_counts(tmp_path):
    acc = np.tile(np.arange(1.0, 11.0), (10, 1))

    candidates, _ = _dem_area(tmp_path, acc)

    assert candidates == []


def test_the_upstream_area_is_the_cell_count_times_the_cell_area():
    cells = np.array([[1.0, 100.0], [75.0, 125.0]])

    assert accumulation_to_area_km2(cells, cell_area_m2=1_000_000.0).tolist() == cells.tolist()
    with pytest.raises(ValueError, match="cell_area_m2"):
        accumulation_to_area_km2(cells, cell_area_m2=0.0)


def _backend(*, raster: bool, flow: bool):
    """A delineation backend that writes raw counts, through either of its two routes."""
    counts = np.full((3, 3), 500.0)
    parts = {}
    if raster:
        parts["raster"] = SimpleNamespace(
            read_raster=lambda path: counts,
            write_raster=lambda data, path: write_geotiff(path, data, crs=None),
        )
        parts["flow"] = SimpleNamespace(d8_flow_accumulation_raster=lambda data, log: data)
    elif flow:
        parts["flow"] = SimpleNamespace(
            d8_flow_accumulation=lambda src, dst, log: write_geotiff(dst, counts, crs=None)
        )
    return SimpleNamespace(**parts)


@pytest.mark.parametrize("route", ["raster", "flow"])
def test_a_log_scaled_accumulation_is_rebuilt_in_cell_counts(tmp_path, route):
    rasterio = pytest.importorskip("rasterio")
    log_acc = write_accumulation_raster(tmp_path / "acc.tif", np.full((3, 3), 4.6))
    backend = _backend(raster=route == "raster", flow=route == "flow")

    path = ensure_raw_accumulation_cells(
        flow_products=site_flow_products(log_acc),
        output_dir=tmp_path / "flow",
        backend=backend,
        crs_project="EPSG:2154",
    )

    assert path == tmp_path / "flow" / "dem_acc_cells.tif"
    with rasterio.open(path) as src:
        assert src.read(1).max() == 500.0
        assert str(src.crs) == "EPSG:2154"
    same = ensure_raw_accumulation_cells(
        flow_products=site_flow_products(log_acc), output_dir=tmp_path / "flow", backend=None
    )
    assert same == path


def test_a_raw_accumulation_is_used_as_it_is(tmp_path):
    raw = write_accumulation_raster(tmp_path / "acc.tif", np.full((3, 3), 500.0))

    assert (
        ensure_raw_accumulation_cells(
            flow_products=site_flow_products(raw), output_dir=tmp_path / "flow"
        )
        == raw
    )


def test_a_backend_without_an_accumulation_is_refused(tmp_path):
    (tmp_path / "missing.tif").write_text("not a raster", encoding="utf-8")
    with pytest.raises(TypeError, match="d8_flow_accumulation"):
        ensure_raw_accumulation_cells(
            flow_products=site_flow_products(tmp_path / "missing.tif"),
            output_dir=tmp_path / "flow",
            backend=_backend(raster=False, flow=False),
        )
