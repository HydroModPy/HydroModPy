"""Active-cell views of a stored cell flux, as masks and metrics over a four-cell mesh.

A cell is active when its accumulation flux is at least the threshold (m3/s). The
mesh is a 2 x 2 block of unit squares (m) whose third cell is outside the catchment.
Fluxes come from three timesteps. The expected values are counted by hand from them.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)
from hydromodpy.results.derive import views
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import runs

__all__ = ["runs"]

OUTSIDE = -9999.0
TOPOGRAPHY = np.array([100.0, 100.0, OUTSIDE, 100.0])

# Accumulation flux of the four cells at three timesteps. Cell 2 is outside.
ACCUMULATION_FRAMES = [
    np.array([0.0, 2.0, 9.0, 0.0]),
    np.array([1.0, 2.0, 9.0, 0.0]),
    np.array([0.0, 2.0, 9.0, 4.0]),
]


def flux_run(runs, *, with_mesh=False, with_network=False, **facts) -> Run:
    """A four-cell run with accumulation flux, optionally with a plot mesh and a mapped stream.

    The mapped stream runs through the centres of cells 1 and 3.
    """
    sid = runs.open(n_cells=4, n_layers=1, n_timesteps=3, **facts).sim_id
    store = runs.store(sid)
    if with_mesh:
        vertices = np.array([[x, y, 0.0] for y in range(3) for x in range(3)])
        faces = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
        store.write_mesh(sid, vertices, faces, TOPOGRAPHY)
        # Same frame as the network features: network metrics overlay the two and
        # refuse to guess.
        store.write_geographic_metadata(sid, {"crs_proj": "EPSG:2154"})
    sz = store.open_zarr(sid)
    try:
        sz.root.require_group("mesh").create_array("topography", data=TOPOGRAPHY, overwrite=True)
        for timestep, values in enumerate(ACCUMULATION_FRAMES):
            sz.write_field(
                "drain_accumulation_flux",
                timestep,
                values,
                n_timesteps=3 if timestep == 0 else None,
                subgroup="derived",
            )
    finally:
        sz.close()
    if with_network:
        reference = gpd.GeoDataFrame(
            {"id": [1]}, geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])], crs="EPSG:2154"
        )
        store.write_geographic_feature(sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference)
    return Run(sid, runs.reader())


ACTIVE_METRICS = {
    "source_variable": "drain_accumulation_flux",
    "n_timesteps": 3,
    "catchment_cell_count": 3,
    "active_cell_count_mean": 5.0 / 3.0,
    "active_cell_count_max": 2,
    "active_cell_count_last": 2,
    "active_cell_count_any": 3,
    "persistent_cell_count": 1,
    "always_active_cell_count": 1,
    "perennial_cell_count": 1,
    "drainage_density_mean_pct": 100.0 * 5.0 / 9.0,
    "drainage_density_max_pct": 100.0 * 2.0 / 3.0,
    "drainage_density_last_pct": 100.0 * 2.0 / 3.0,
    "active_any_ratio": 1.0,
    "persistent_ratio": 1.0 / 3.0,
    "always_active_ratio": 1.0 / 3.0,
    "perennial_ratio": 1.0 / 3.0,
    "persistence_mean": 5.0 / 9.0,
    "persistence_max": 1.0,
}

OVERLAP_METRICS = {
    "network_role": "reference",
    "catchment_cell_count": 3,
    "active_cell_count": 1,
    "network_cell_count": 2,
    "overlap_cell_count": 1,
    "missing_network_cell_count": 1,
    "extra_active_cell_count": 0,
    "network_coverage_ratio": 0.5,
    "active_precision_ratio": 1.0,
    "cell_f1_ratio": 2.0 / 3.0,
    "cell_jaccard_ratio": 0.5,
}

DISTANCE_METRICS = {
    "network_role": "reference",
    "distance_method": "planar_cell_centroid_to_network",
    "catchment_cell_count": 3,
    "active_cell_count": 1,
    "network_cell_count": 2,
    "sim_to_network_sample_count": 1,
    "network_to_sim_sample_count": 2,
    "sim_to_network_distance_mean_m": 0.0,
    "network_to_sim_distance_mean_m": 0.25,
    "network_to_sim_distance_max_m": 0.5,
    "bidirectional_distance_mean_m": 0.125,
    "bidirectional_distance_absolute_difference_m": 0.25,
    "planar_distance_ratio": None,
    "planar_distance_log10_ratio": None,
}


def test_active_metrics_from_accumulation_flux(runs):
    sim = flux_run(runs)

    metrics = views.cell_field_active_metrics(sim, threshold=0.5, persistence_threshold=0.5)

    for key, expected in ACTIVE_METRICS.items():
        assert metrics[key] == pytest.approx(expected), key


MASKS = [
    pytest.param("last", {}, [0.0, 1.0, np.nan, 1.0], id="last"),
    pytest.param("any", {}, [1.0, 1.0, np.nan, 1.0], id="any"),
    pytest.param(
        "persistent", {"persistence_threshold": 0.5}, [0.0, 1.0, np.nan, 0.0], id="persistent"
    ),
    pytest.param("always_active", {}, [0.0, 1.0, np.nan, 0.0], id="always active"),
    pytest.param("perennial", {}, [0.0, 1.0, np.nan, 0.0], id="perennial"),
    pytest.param("persistence", {}, [1 / 3, 1.0, np.nan, 1 / 3], id="persistence fraction"),
]


@pytest.mark.parametrize(("mode", "kwargs", "expected"), MASKS)
def test_active_mask_modes(runs, mode, kwargs, expected):
    sim = flux_run(runs)

    mask = views.cell_field_active_mask(sim, threshold=0.5, mode=mode, **kwargs)

    np.testing.assert_allclose(mask, expected)


def test_default_mask_follows_the_flow_regime(runs):
    transient = flux_run(runs, flow_regime="transient")
    steady = flux_run(runs, flow_regime="steady")

    np.testing.assert_allclose(
        views.cell_field_active_mask(transient, threshold=0.5), [0.0, 1.0, np.nan, 0.0]
    )
    np.testing.assert_allclose(
        views.cell_field_active_mask(steady, threshold=0.5), [0.0, 1.0, np.nan, 1.0]
    )


def test_overlap_with_the_reference_network_by_default(runs):
    sim = flux_run(runs, with_mesh=True, with_network=True)

    metrics = views.cell_field_network_overlap_metrics(
        sim, threshold=0.5, mode="persistent", persistence_threshold=0.5
    )

    for key, expected in OVERLAP_METRICS.items():
        assert metrics[key] == pytest.approx(expected), key


def test_distance_to_the_reference_network(runs):
    sim = flux_run(runs, with_mesh=True, with_network=True)

    metrics = views.cell_field_network_distance_metrics(
        sim, threshold=0.5, mode="persistent", persistence_threshold=0.5
    )

    for key, expected in DISTANCE_METRICS.items():
        assert metrics[key] == pytest.approx(expected), key
