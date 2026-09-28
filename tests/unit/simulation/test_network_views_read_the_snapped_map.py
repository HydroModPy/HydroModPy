"""The network views of a run follow ``[geographic.snap_streams]``.

In ``apply`` the overlap and distance metrics of the mapped roles read the
snapped map the run stored. In ``diagnose`` and ``off`` they read the raw map,
and ``off`` returns the numbers it always returned.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from hydromodpy.results.derive import views
from hydromodpy.results.derive.snapped_network import SNAPPED_NETWORK_FEATURES
from hydromodpy.results.run import Run
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)

from ._test_simulation_api_builders import _register, catalog
from .test_simulation_cell_field_views import _write_active_accumulation_flux_case

__all__ = ["catalog"]

OVERLAP = {"threshold": 0.5, "mode": "persistent", "persistence_threshold": 0.5}


def _run(catalog, mode: str | None, *, store_snapped: bool = True) -> Run:
    snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3, config_snapshot=snapshot)
    _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
    # The raw map crosses cells 1 and 3; the snap moved cell 3 onto cell 1.
    catalog.write_geographic_feature(
        sid,
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        gpd.GeoDataFrame(
            {"id": [1]}, geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])], crs="EPSG:2154"
        ),
    )
    if store_snapped:
        catalog.write_geographic_feature(
            sid,
            SNAPPED_NETWORK_FEATURES["maximal"],
            gpd.GeoDataFrame(
                {
                    "raw_cell": [1, 3],
                    "snapped_cell": [1, 1],
                    "status": ["unchanged", "merged"],
                    "displacement_m": [0.0, 1.0],
                    "raw_x": [1.5, 1.5],
                    "raw_y": [0.5, 1.5],
                    "accumulation_percentile": [90.0, 90.0],
                },
                geometry=[Point(1.5, 0.5), Point(1.5, 0.5)],
                crs="EPSG:2154",
            ),
        )
    return Run(sid, catalog)


def test_apply_reads_the_snapped_map(catalog) -> None:
    metrics = views.cell_field_network_overlap_metrics(_run(catalog, "apply"), **OVERLAP)

    assert metrics["network_map"] == "snapped"
    assert metrics["snap_mode"] == "apply"
    assert metrics["network_cell_count"] == 1
    assert metrics["network_coverage_ratio"] == pytest.approx(1.0)
    assert metrics["cell_jaccard_ratio"] == pytest.approx(1.0)


def test_apply_distances_read_the_snapped_map(catalog) -> None:
    metrics = views.cell_field_network_distance_metrics(_run(catalog, "apply"), **OVERLAP)

    assert metrics["network_map"] == "snapped"
    assert metrics["network_cell_count"] == 1
    assert metrics["network_to_sim_distance_mean_m"] == pytest.approx(0.0)


@pytest.mark.parametrize("mode", [None, "off", "diagnose"])
def test_off_and_diagnose_read_the_raw_map_as_before(catalog, mode) -> None:
    run = _run(catalog, mode)
    overlap = views.cell_field_network_overlap_metrics(run, **OVERLAP)
    distance = views.cell_field_network_distance_metrics(run, **OVERLAP)

    assert overlap["network_map"] == "raw"
    assert overlap["snap_mode"] == (mode or "off")
    # The numbers of the unsnapped view test, unchanged.
    assert overlap["network_cell_count"] == 2
    assert overlap["network_coverage_ratio"] == pytest.approx(0.5)
    assert overlap["cell_jaccard_ratio"] == pytest.approx(0.5)
    assert distance["network_to_sim_distance_mean_m"] == pytest.approx(0.25)


def test_apply_without_a_stored_map_reads_the_raw_one_and_says_so(catalog, caplog) -> None:
    run = _run(catalog, "apply", store_snapped=False)
    with caplog.at_level(logging.WARNING):
        metrics = views.cell_field_network_overlap_metrics(run, **OVERLAP)

    assert metrics["network_map"] == "raw"
    assert metrics["network_cell_count"] == 2
    assert "stored no snapped" in caplog.text


def test_a_supplied_network_is_read_as_given(catalog) -> None:
    supplied = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])], crs="EPSG:2154"
    )
    metrics = views.cell_field_network_distance_metrics(
        _run(catalog, "apply"), network_gdf=supplied, **OVERLAP
    )

    assert metrics["network_map"] == "supplied"
    assert metrics["network_cell_count"] == 2
