"""High-level orchestration for the display package.

This module is the coordination layer between simulation results and the
generic figure functions in :mod:`hydromodpy.display.figures`.

Each suite follows the same pattern:
- inspect the normalized display options;
- locate the post-processed files produced by the simulation;
- extract data into generic types (arrays, DataFrames);
- call the generic figure helpers.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.display.adapters import (
    observed_discharge_series,
    observed_piezometry_series,
)
from hydromodpy.display.common import (
    _extract_recharge_series_m_per_day,
    resolve_flow_base_raster,
    resolve_model_figure_dir,
)
from hydromodpy.display.figures.animation import build_gif, build_plotly_slider
from hydromodpy.display.figures.cross_section import plot_cross_section
from hydromodpy.display.figures.maps import plot_pathlines_map
from hydromodpy.display.figures.timeseries import plot_discharge, plot_piezometry
from hydromodpy.display.options import DisplayOptions
from hydromodpy.display.transport_plots import plot_concentration_frames


# ------------------------------------------------------------------
# Internal helpers — data extraction
# ------------------------------------------------------------------

def _resolve_flow_model(result):
    """Return the configured flow model using explicit solver lookup."""
    flow_model = result.get_model_for_solver("modflownwt")
    if flow_model is None:
        flow_model = result.get_model_for_solver("modflow6")
    return flow_model


def _load_observed_streamflow(result) -> pd.DataFrame | None:
    """Load observed discharge from PointRecords.

    Returns a monthly discharge DataFrame or *None*.
    """
    hydrometry = getattr(result.loaded_data, "hydrometry", None)
    if not hydrometry:
        return None
    records = getattr(hydrometry, "points", hydrometry)
    if not records:
        return None
    area_m2 = float(result.setup.geographic.catch_area) * 1_000_000
    return observed_discharge_series(records, freq="ME", area_m2=area_m2)


def _load_flow_timeseries(result) -> pd.DataFrame:
    """Load the simulated flow time series exported by post-processing."""
    run_id = _resolve_flow_model(result).model_name
    smod_path = (
        result.setup.workspace.simulations_folder
        / run_id
        / "_postprocess"
        / "_timeseries"
        / "_simulated_timeseries.csv"
    )
    return pd.read_csv(smod_path, sep=";", index_col=0, parse_dates=True)


def _extract_cross_section_data(
    dem_path: Path,
    wt_path: Path,
    x_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract 1-D cross-section arrays from DEM and water-table files."""
    import rasterio

    watertable = np.load(wt_path, allow_pickle=True).item()
    with rasterio.open(dem_path) as dem_src:
        dem_data = dem_src.read(1)
        nodata = dem_src.nodata
        row_spacing = abs(float(dem_src.transform.e)) if dem_src.transform.e else 1.0

    wt = watertable[2].astype(float)
    dem = dem_data.astype(float)
    if nodata is not None:
        dem[np.isclose(dem, float(nodata))] = np.nan
    else:
        dem[dem < 0] = np.nan
    wt[wt < 0] = np.nan

    if x_index is None:
        x_index = dem.shape[1] // 2
    x_index = int(np.clip(x_index, 0, max(dem.shape[1] - 1, 0)))

    x_coords = np.arange(dem.shape[0], dtype=float) * row_spacing
    return dem[:, x_index], wt[:, x_index], x_coords


def _prepare_streamflow_series(
    simulated_timeseries: pd.DataFrame,
    factor: int = 30,
) -> tuple[pd.Series, pd.Series]:
    """Convert raw simulated timeseries to plotting-ready Series.

    Returns *(outflow_series, recharge_series)* both in mm/month.
    """
    recharge = simulated_timeseries["recharge"] * factor * 1000
    outflow = (
        simulated_timeseries["outflow_drain"] + simulated_timeseries["runoff"]
    ) * factor * 1000
    return outflow, recharge


# ------------------------------------------------------------------
# Suites
# ------------------------------------------------------------------

def plot_flow_suite(result, options: DisplayOptions) -> None:
    """Run all enabled flow figures for one completed simulation result."""
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id)
    base_raster = resolve_flow_base_raster(flow_model, result.setup.geographic)
    simulated_timeseries = _load_flow_timeseries(result)
    observed_streamflow = _load_observed_streamflow(result)

    if options.flow.is_enabled("cross_section", default=True):
        wt_path = (
            result.setup.workspace.simulations_folder
            / run_id
            / "_postprocess"
            / "watertable_elevation.npy"
        )
        dem_section, wt_section, x_coords = _extract_cross_section_data(
            base_raster, wt_path,
        )
        plot_cross_section(
            dem_section=dem_section,
            wt_section=wt_section,
            x_coords=x_coords,
            options=options,
            save_path=output_dir / "cross_section.png",
        )

    if options.flow.is_enabled("streamflow", default=True) and observed_streamflow is not None:
        outflow, recharge = _prepare_streamflow_series(simulated_timeseries)
        plot_discharge(
            observed_df=observed_streamflow,
            simulated_series=outflow,
            recharge_series=recharge,
            model_label=run_id.upper(),
            ylabel="Q / A [mm/month]",
            options=options,
            save_path=output_dir / "streamflow.png",
        )

    if options.flow.is_enabled("piezometry", default=True):
        obs_piezo = None
        piezometry = getattr(result.loaded_data, "piezometry", None)
        if piezometry:
            obs_piezo = observed_piezometry_series(piezometry, freq="ME")

        _, recharge = _prepare_streamflow_series(simulated_timeseries)
        wt_depth = simulated_timeseries["watertable_depth"]
        plot_piezometry(
            observed_df=obs_piezo,
            simulated_series=wt_depth,
            recharge_series=recharge,
            model_label=run_id.upper(),
            options=options,
            save_path=output_dir / "piezometry.png",
        )


def plot_particles_suite(result, options: DisplayOptions) -> None:
    """Run all enabled particle-tracking outputs for one simulation result."""
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id)
    particles_dir = (
        result.setup.workspace.simulations_folder
        / run_id
        / "_postprocess"
        / "_particles"
    )

    if not options.particles.is_enabled("pathlines", default=False):
        return

    import geopandas as gpd

    pathlines_gdf = gpd.read_file(particles_dir / "pathlines_weighted.shp")
    endpoints_gdf = gpd.read_file(particles_dir / "starting_weighted.shp")

    plot_pathlines_map(
        dem_path=resolve_flow_base_raster(flow_model, result.setup.geographic),
        watershed_shp=result.setup.geographic.watershed_shp,
        pathlines_gdf=pathlines_gdf,
        endpoints_gdf=endpoints_gdf,
        options=options,
        save_path=output_dir / "pathlines.png",
    )


def plot_transport_suite(result, options: DisplayOptions) -> None:
    """Run transport concentration exports and derived animations.

    Frame generation is shared by static images, GIF, and HTML slider.
    """
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    transport_model = result.get_model_for_solver("mt3dms")
    if transport_model is None:
        transport_model = result.get_model_for_solver("modflow6gwt")
    if transport_model is None:
        return

    run_concentration = options.transport.is_enabled("concentration", default=False)
    run_gif = options.transport.is_enabled("gif", default=False)
    run_web_animation = options.transport.is_enabled("web_animation", default=False)
    if not any([run_concentration, run_gif, run_web_animation]):
        return

    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id) / "transport"
    save_frame_files = options.save or run_gif or run_web_animation
    show_last_frame = run_concentration and options.show

    frame_paths = plot_concentration_frames(
        model_transport=transport_model,
        model_modflow=flow_model,
        geographic=result.setup.geographic,
        hydrography=result.loaded_data.hydrography,
        recharge_series=_extract_recharge_series_m_per_day(result.loaded_data.recharge),
        base_raster_path=resolve_flow_base_raster(flow_model, result.setup.geographic),
        output_dir=output_dir,
        prefix="concentration",
        dpi=options.dpi,
        save_frames=save_frame_files,
        show_last_frame=show_last_frame,
    )

    if run_gif:
        build_gif(
            frame_paths=frame_paths,
            gif_path=output_dir / "concentration.gif",
        )

    if run_web_animation:
        html_path = output_dir / "concentration_slider.html" if options.save else None
        build_plotly_slider(
            frame_paths=frame_paths,
            html_path=html_path,
            show_in_browser=options.show,
        )
