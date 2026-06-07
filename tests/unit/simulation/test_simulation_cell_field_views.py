from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.results import views
from hydromodpy.results.run import Run
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


def _write_active_accumulation_flux_case(catalog, sid, *, write_plot_mesh=False):
    if write_plot_mesh:
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [0.0, 2.0, 0.0],
                [1.0, 2.0, 0.0],
                [2.0, 2.0, 0.0],
            ],
            dtype="float64",
        )
        face_node_connectivity = np.array(
            [
                [0, 1, 4, 3],
                [1, 2, 5, 4],
                [3, 4, 7, 6],
                [4, 5, 8, 7],
            ],
            dtype="int32",
        )
        catalog.write_mesh(
            sid,
            vertices,
            face_node_connectivity,
            np.array([100.0, 100.0, -9999.0, 100.0], dtype="float64"),
        )
    sz = catalog.open_zarr(sid)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array(
            "topography",
            data=np.array([100.0, 100.0, -9999.0, 100.0], dtype="float64"),
            overwrite=True,
        )
        frames = [
            np.array([0.0, 2.0, 9.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 9.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 9.0, 4.0], dtype="float64"),
        ]
        for timestep, values in enumerate(frames):
            sz.write_field(
                "accumulation_flux",
                timestep,
                values,
                n_timesteps=3 if timestep == 0 else None,
                subgroup="derived",
            )
    finally:
        sz.close()


def _write_release_flux_case(catalog, sid, *, write_plot_mesh=False):
    _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=write_plot_mesh)
    sz = catalog.open_zarr(sid)
    try:
        frames = [
            np.array([0.0, 0.0, 9.0, 3.0], dtype="float64"),
            np.array([0.0, 2.0, 9.0, 3.0], dtype="float64"),
            np.array([0.0, 0.0, 9.0, 3.0], dtype="float64"),
        ]
        for timestep, values in enumerate(frames):
            sz.write_field(
                "release_flux",
                timestep,
                values,
                n_timesteps=3 if timestep == 0 else None,
                subgroup="derived",
            )
    finally:
        sz.close()


class TestSimulationCellFieldViews:
    def test_cell_field_active_metrics_from_accumulation_flux(self, catalog):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid)

        sim = Run(sid, catalog)
        metrics = views.cell_field_active_metrics(
            sim,
            threshold=0.5,
            persistence_threshold=0.5,
        )

        assert metrics["source_variable"] == "accumulation_flux"
        assert metrics["n_timesteps"] == 3
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count_mean"] == pytest.approx(5.0 / 3.0)
        assert metrics["active_cell_count_max"] == 2
        assert metrics["active_cell_count_last"] == 2
        assert metrics["active_cell_count_any"] == 3
        assert metrics["persistent_cell_count"] == 1
        assert metrics["always_active_cell_count"] == 1
        assert metrics["perennial_cell_count"] == 1
        assert metrics["drainage_density_mean_pct"] == pytest.approx(100.0 * 5.0 / 9.0)
        assert metrics["drainage_density_max_pct"] == pytest.approx(100.0 * 2.0 / 3.0)
        assert metrics["drainage_density_last_pct"] == pytest.approx(100.0 * 2.0 / 3.0)
        assert metrics["active_any_ratio"] == pytest.approx(1.0)
        assert metrics["persistent_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["always_active_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["perennial_ratio"] == pytest.approx(1.0 / 3.0)
        assert metrics["persistence_mean"] == pytest.approx(5.0 / 9.0)
        assert metrics["persistence_max"] == pytest.approx(1.0)

    def test_cell_field_active_mask_modes(self, catalog):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid)

        sim = Run(sid, catalog)

        np.testing.assert_allclose(
            views.cell_field_active_mask(sim, threshold=0.5, mode="last"),
            np.array([0.0, 1.0, np.nan, 1.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(sim, threshold=0.5, mode="any"),
            np.array([1.0, 1.0, np.nan, 1.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(
                sim,
                threshold=0.5,
                mode="persistent",
                persistence_threshold=0.5,
            ),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(sim, threshold=0.5, mode="always_active"),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(sim, threshold=0.5, mode="perennial"),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(sim, threshold=0.5, mode="persistence"),
            np.array([1.0 / 3.0, 1.0, np.nan, 1.0 / 3.0]),
        )

    def test_cell_field_active_mask_default_is_regime_aware(self, catalog):
        transient_sid = _register(
            catalog,
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            flow_regime="transient",
        )
        steady_sid = _register(
            catalog,
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            flow_regime="steady",
        )
        _write_active_accumulation_flux_case(catalog, transient_sid)
        _write_active_accumulation_flux_case(catalog, steady_sid)

        transient = Run(transient_sid, catalog)
        steady = Run(steady_sid, catalog)

        np.testing.assert_allclose(
            views.cell_field_active_mask(transient, threshold=0.5),
            np.array([0.0, 1.0, np.nan, 0.0]),
        )
        np.testing.assert_allclose(
            views.cell_field_active_mask(steady, threshold=0.5),
            np.array([0.0, 1.0, np.nan, 1.0]),
        )

    def test_cell_field_network_overlap_metrics_against_reference_role_by_default(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        metrics = views.cell_field_network_overlap_metrics(
            sim,
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["network_role"] == "reference"
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count"] == 1
        assert metrics["network_cell_count"] == 2
        assert metrics["overlap_cell_count"] == 1
        assert metrics["missing_network_cell_count"] == 1
        assert metrics["extra_active_cell_count"] == 0
        assert metrics["network_coverage_ratio"] == pytest.approx(0.5)
        assert metrics["active_precision_ratio"] == pytest.approx(1.0)
        assert metrics["cell_f1_ratio"] == pytest.approx(2.0 / 3.0)
        assert metrics["cell_jaccard_ratio"] == pytest.approx(0.5)

    def test_cell_field_network_distance_metrics_against_reference_role(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        metrics = views.cell_field_network_distance_metrics(
            sim,
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["network_role"] == "reference"
        assert metrics["distance_method"] == "planar_cell_centroid_to_network"
        assert metrics["catchment_cell_count"] == 3
        assert metrics["active_cell_count"] == 1
        assert metrics["network_cell_count"] == 2
        assert metrics["sim_to_network_sample_count"] == 1
        assert metrics["network_to_sim_sample_count"] == 2
        assert metrics["sim_to_network_distance_mean_m"] == pytest.approx(0.0)
        assert metrics["network_to_sim_distance_mean_m"] == pytest.approx(0.25)
        assert metrics["network_to_sim_distance_max_m"] == pytest.approx(0.5)
        assert metrics["bidirectional_distance_mean_m"] == pytest.approx(0.125)
        assert metrics["bidirectional_distance_absolute_difference_m"] == pytest.approx(0.25)
        assert metrics["planar_distance_ratio"] is None
        assert metrics["planar_distance_log10_ratio"] is None

    def test_release_flux_network_overlap_metrics_use_release_flux(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_release_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        metrics = views.release_flux_network_overlap_metrics(
            sim,
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["source_variable"] == "release_flux"
        assert metrics["active_cell_count"] == 1
        assert metrics["network_cell_count"] == 2
        assert metrics["overlap_cell_count"] == 1
        assert metrics["cell_jaccard_ratio"] == pytest.approx(0.5)

    def test_release_flux_network_distance_metrics_have_no_buffer_parameter(
        self,
        catalog,
    ):
        sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3)
        _write_release_flux_case(catalog, sid, write_plot_mesh=True)
        reference = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(1.5, 0.5), (1.5, 1.5)])],
            crs="EPSG:2154",
        )
        catalog.write_geographic_feature(
            sid, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, reference
        )

        sim = Run(sid, catalog)
        metrics = views.release_flux_network_distance_metrics(
            sim,
            threshold=0.5,
            mode="persistent",
            persistence_threshold=0.5,
        )

        assert metrics["source_variable"] == "release_flux"
        assert metrics["network_buffer_m"] == 0.0
        assert metrics["active_cell_count"] == 1
        assert metrics["sim_to_network_distance_mean_m"] == pytest.approx(0.0)
