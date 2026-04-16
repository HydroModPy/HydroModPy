"""Tests for the generic figure functions in hydromodpy.analysis.display.figures."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest


class TestCrossSection:
    def test_render_cross_section_draws_on_axes(self):
        from hydromodpy.analysis.display.figures.cross_section import render_cross_section

        fig, ax = plt.subplots()
        x = np.arange(10, dtype=float)
        dem = np.linspace(50, 20, 10)
        wt = np.linspace(45, 15, 10)
        render_cross_section(ax, dem_section=dem, wt_section=wt, x_coords=x)
        assert len(ax.lines) > 0
        plt.close(fig)

    def test_render_cross_section_handles_nan(self):
        from hydromodpy.analysis.display.figures.cross_section import render_cross_section

        fig, ax = plt.subplots()
        x = np.arange(5, dtype=float)
        dem = np.array([np.nan, np.nan, np.nan, np.nan, np.nan])
        wt = np.array([np.nan, np.nan, np.nan, np.nan, np.nan])
        render_cross_section(ax, dem_section=dem, wt_section=wt, x_coords=x)
        plt.close(fig)


class TestBoussinesqState:
    def test_render_boussinesq_state_draws_map_and_profile(self):
        from hydromodpy.analysis.display.figures.boussinesq import render_boussinesq_state

        fig, (ax_map, ax_profile) = plt.subplots(1, 2)
        render_boussinesq_state(
            ax_map,
            ax_profile,
            node_x_m=np.array([0.0, 1.0, 0.0, 1.0]),
            node_y_m=np.array([0.0, 0.0, 1.0, 1.0]),
            triangles=np.array([[0, 1, 2], [1, 3, 2]], dtype=int),
            cell_head_m=np.array([9.0, 8.5]),
            cell_centroid_x_m=np.array([1.0 / 3.0, 2.0 / 3.0]),
            cell_z_top_m=np.array([10.0, 10.0]),
            cell_z_bottom_m=np.array([5.0, 5.0]),
        )
        assert len(ax_map.collections) > 0
        assert len(ax_profile.lines) > 0
        plt.close(fig)

    def test_render_boussinesq_diagnostics_draws_maps(self):
        from hydromodpy.analysis.display.figures.boussinesq import (
            render_boussinesq_diagnostics,
        )

        fig, axs = plt.subplots(2, 2)
        render_boussinesq_diagnostics(
            axs,
            node_x_m=np.array([0.0, 1.0, 0.0, 1.0]),
            node_y_m=np.array([0.0, 0.0, 1.0, 1.0]),
            triangles=np.array([[0, 1, 2], [1, 3, 2]], dtype=int),
            cell_head_m=np.array([9.0, 8.5]),
            cell_z_top_m=np.array([10.0, 10.0]),
            cell_z_bottom_m=np.array([5.0, 5.0]),
            cell_area_m2=np.array([0.5, 0.5]),
            cell_saturation_excess_rate_m_s=np.array([1.0e-8, 2.0e-8]),
            cell_drainage_flux_m3_s=np.array([1.0e-6, 2.0e-6]),
        )
        for ax in np.asarray(axs, dtype=object).reshape(-1):
            assert len(ax.collections) > 0
        plt.close(fig)

    def test_render_boussinesq_edge_flux_map_draws_collections(self):
        from hydromodpy.analysis.display.figures.boussinesq import (
            render_boussinesq_edge_flux_map,
        )

        fig, ax = plt.subplots()
        render_boussinesq_edge_flux_map(
            ax,
            node_x_m=np.array([0.0, 1.0, 0.0, 1.0]),
            node_y_m=np.array([0.0, 0.0, 1.0, 1.0]),
            edge_node_a_indices=np.array([0, 1, 2, 0, 1]),
            edge_node_b_indices=np.array([1, 3, 3, 2, 2]),
            boundary_edge_mask=np.array([True, True, True, True, False]),
            internal_edge_flux_m3_s=np.array([0.0, 0.0, 0.0, 0.0, 3.0e-4]),
            boundary_edge_flux_m3_s=np.array([1.0e-4, -2.0e-4, 0.0, 3.0e-4, 0.0]),
        )
        assert len(ax.collections) > 0
        plt.close(fig)


class TestFlowDiagnostics:
    def test_render_flow_mass_balance_draws_lines(self):
        from hydromodpy.analysis.display.figures.flow_diagnostics import (
            render_flow_mass_balance,
        )

        fig, ax = plt.subplots()
        render_flow_mass_balance(
            ax,
            time_values=np.array([1.0, 2.0, 3.0]),
            components_by_name={
                "Recharge": np.array([1.0, 1.5, 1.2]),
                "Drainage": np.array([-0.4, -0.8, -0.7]),
            },
            net_series=np.array([0.1, -0.05, 0.02]),
        )
        assert len(ax.lines) >= 3
        plt.close(fig)

    def test_render_flow_probe_timeseries_draws_lines(self):
        from hydromodpy.analysis.display.figures.flow_diagnostics import (
            render_flow_probe_timeseries,
        )

        fig, ax = plt.subplots()
        render_flow_probe_timeseries(
            ax,
            time_values=np.array([1.0, 2.0, 3.0]),
            series_by_label={
                "Cell 1": np.array([9.8, 9.6, 9.5]),
                "Cell 2": np.array([9.2, 9.1, 9.0]),
            },
            ylabel="Head [m]",
        )
        assert len(ax.lines) == 2
        plt.close(fig)


class TestDischarge:
    def test_render_discharge_overview_mode(self):
        from hydromodpy.analysis.display.figures.timeseries import render_discharge

        fig, ax = plt.subplots()
        dates = pd.date_range("2020-01-01", periods=12, freq="ME")
        df = pd.DataFrame({"station_A": np.random.rand(12)}, index=dates)
        render_discharge(ax, observed_df=df)
        assert ax.get_title() == "Observed discharge"
        plt.close(fig)

    def test_render_discharge_simulation_mode(self):
        from hydromodpy.analysis.display.figures.timeseries import render_discharge

        fig, ax = plt.subplots()
        dates = pd.date_range("2020-01-01", periods=12, freq="ME")
        obs = pd.Series(np.random.rand(12), index=dates, name="Q")
        sim = pd.Series(np.random.rand(12), index=dates)
        render_discharge(ax, observed_df=obs, simulated_series=sim, model_label="TEST")
        assert ax.get_title() == "TEST"
        plt.close(fig)

    def test_render_discharge_empty(self):
        from hydromodpy.analysis.display.figures.timeseries import render_discharge

        fig, ax = plt.subplots()
        render_discharge(ax)
        # Should show "No discharge data" text
        texts = [t.get_text() for t in ax.texts]
        assert any("No discharge" in t for t in texts)
        plt.close(fig)


class TestPiezometry:
    def test_render_piezometry_overview_mode(self):
        from hydromodpy.analysis.display.figures.timeseries import render_piezometry

        fig, ax = plt.subplots()
        dates = pd.date_range("2020-01-01", periods=12, freq="ME")
        df = pd.DataFrame({"well_1": np.random.rand(12)}, index=dates)
        render_piezometry(ax, observed_df=df)
        assert "piezometric" in ax.get_title().lower()
        plt.close(fig)

    def test_render_piezometry_simulation_mode(self):
        from hydromodpy.analysis.display.figures.timeseries import render_piezometry

        fig, ax = plt.subplots()
        dates = pd.date_range("2020-01-01", periods=12, freq="ME")
        sim = pd.Series(np.random.rand(12), index=dates)
        render_piezometry(ax, simulated_series=sim, model_label="NWT")
        assert ax.get_title() == "NWT"
        plt.close(fig)


class TestClimaticSummary:
    def test_render_climatic_summary_with_data(self):
        from hydromodpy.analysis.display.figures.timeseries import render_climatic_summary

        fig, ax = plt.subplots()
        precip = {m: float(m * 10) for m in range(1, 13)}
        etp = {m: float(m * 5) for m in range(1, 13)}
        render_climatic_summary(ax, monthly_precip=precip, monthly_etp=etp)
        assert len(ax.patches) > 0  # bars were drawn
        plt.close(fig)

    def test_render_climatic_summary_empty(self):
        from hydromodpy.analysis.display.figures.timeseries import render_climatic_summary

        fig, ax = plt.subplots()
        render_climatic_summary(ax)
        texts = [t.get_text() for t in ax.texts]
        assert any("No climatic" in t for t in texts)
        plt.close(fig)


class TestIntermittency:
    def test_render_intermittency_single_station(self):
        from hydromodpy.analysis.display.figures.timeseries import render_intermittency

        fig, ax = plt.subplots()
        df = pd.DataFrame({
            "datetime": pd.date_range("2020-01-01", periods=5, freq="ME"),
            "station_id": ["S1"] * 5,
            "value": [1, 2, 3, 4, 5],
        })
        render_intermittency(ax, records_df=df, station_id="S1")
        # Title can be in _left_title (ultraplot) or main title (mpl)
        titles = [ax.get_title(), ax.get_title(loc="left")]
        assert any("S1" in t for t in titles)
        assert ax.get_yticks().tolist() == [1, 2, 3, 4, 5]
        plt.close(fig)

    def test_render_intermittency_categorical_yaxis(self):
        from hydromodpy.analysis.display.figures.timeseries import render_intermittency

        fig, ax = plt.subplots()
        df = pd.DataFrame({
            "datetime": pd.date_range("2020-01-01", periods=3, freq="ME"),
            "station_id": ["S1"] * 3,
            "value": [1, 3, 5],
        })
        render_intermittency(ax, records_df=df)
        labels = [t.get_text() for t in ax.get_yticklabels()]
        assert len(labels) == 5
        plt.close(fig)


class TestWaterQuality:
    def test_render_water_quality(self):
        from hydromodpy.analysis.display.figures.timeseries import render_water_quality

        fig, ax = plt.subplots()
        df = pd.DataFrame({
            "datetime": pd.date_range("2020-01-01", periods=4, freq="ME"),
            "variable": ["NO3", "NO3", "SO4", "SO4"],
            "value": [10, 12, 5, 6],
            "unit": ["mg/L", "mg/L", "mg/L", "mg/L"],
            "source_unit": ["ug/L", "ug/L", "mg/L", "mg/L"],
        })
        render_water_quality(ax, records_df=df)
        assert ax.get_title() == "Water quality"
        legend = ax.get_legend()
        assert legend is not None
        labels = [text.get_text() for text in legend.get_texts()]
        assert "NO3 (mg/L; src ug/L)" in labels
        plt.close(fig)


class TestTables:
    def test_render_stats_card(self):
        from hydromodpy.analysis.display.figures.tables import render_stats_card
        from types import SimpleNamespace

        fig, ax = plt.subplots()
        summary = SimpleNamespace(
            watershed_name="Test",
            catchment_area_km2=42.0,
            elevation_min_m=10,
            elevation_max_m=200,
            elevation_mean_m=100,
            n_hydrometry_stations=2,
            n_piezometry_stations=3,
            n_intermittency_stations=1,
            geology_types=["granite"],
            mean_annual_precipitation_mm=800,
            mean_annual_etp_mm=500,
        )
        render_stats_card(ax, summary=summary)
        texts = [t.get_text() for t in ax.texts]
        assert any("Test" in t for t in texts)
        plt.close(fig)

    def test_render_station_inventory_empty(self):
        from hydromodpy.analysis.display.figures.tables import render_station_inventory

        fig, ax = plt.subplots()
        render_station_inventory(ax, inventory=[])
        texts = [t.get_text() for t in ax.texts]
        assert any("No stations" in t for t in texts)
        plt.close(fig)


class TestAnimation:
    def test_build_gif_returns_none_on_empty(self):
        from hydromodpy.analysis.display.figures.animation import build_gif
        from pathlib import Path

        result = build_gif(frame_paths=[], gif_path=Path("/tmp/test.gif"))
        assert result is None

    def test_build_mp4_returns_none_on_empty(self):
        from hydromodpy.analysis.display.figures.animation import build_mp4
        from pathlib import Path

        result = build_mp4(frame_paths=[], mp4_path=Path("/tmp/test.mp4"))
        assert result is None


class TestMakeFigure:
    def test_make_figure_returns_fig_and_axes(self):
        from hydromodpy.analysis.display.common import make_figure, _single_axes

        fig, axs = make_figure(figsize=(4, 3), dpi=72)
        ax = _single_axes(axs)
        assert fig is not None
        assert ax is not None
        plt.close(fig)

    def test_make_figure_multi_axes(self):
        from hydromodpy.analysis.display.common import make_figure

        fig, axs = make_figure(nrows=2, ncols=1, figsize=(4, 6), dpi=72)
        assert fig is not None
        plt.close(fig)
