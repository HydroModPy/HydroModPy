"""High-level orchestration for the display package.

This module is the coordination layer between simulation results and the lower-
level plotting functions.

Each suite follows the same pattern:
- inspect the normalized display options;
- locate the post-processed files produced by the simulation;
- call the specialized plotting helpers for the enabled outputs.

This keeps the plotting functions focused on figure construction, while the
knowledge of result-folder layout stays centralized here.
"""
from __future__ import annotations

import pandas as pd

from hydromodpy.display.common import (
    resolve_flow_base_raster,
    resolve_model_figure_dir,
)
from hydromodpy.display.flow_plots import (
    plot_cross_section,
    plot_piezometry,
    plot_streamflow,
)
from hydromodpy.display.options import DisplayOptions
from hydromodpy.display.particles_plots import plot_pathlines
from hydromodpy.display.transport_plots import (
    build_concentration_gif,
    plot_concentration_frames,
    plot_web_animation,
)


def _resolve_flow_model(result):
    """Return the configured flow model using explicit solver lookup."""

    flow_model = result.get_model_for_solver("modflownwt")
    if flow_model is None:
        flow_model = result.get_model_for_solver("modflow6")
    return flow_model


def _load_observed_streamflow(result) -> pd.DataFrame:
    """Load and normalize the observed discharge series for flow diagnostics.

    The helper reads the reference discharge file used by the current example
    workflows, builds a proper datetime index, then rescales the raw values to
    monthly ``mm/month`` over the modeled catchment area.

    Returning a normalized series here avoids repeating the same data-wrangling
    steps in each flow plotting function.
    """

    area = int(round(result.setup.geographic.catch_area))
    qobs_path = result.cfg.workspace.data_path / "Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt"
    qobs = pd.read_csv(qobs_path, sep=";", header=None)
    qobs.index = pd.to_datetime(qobs[0] + " " + qobs[1], format="%d/%m/%Y %H:%M:%S")
    qobs = qobs[2].to_frame(name="Q")
    qobs = qobs / 1000 / (area * 1_000_000)
    return qobs.resample("ME").mean() * 30 * 1000


def _load_flow_timeseries(result) -> pd.DataFrame:
    """Load the simulated flow time series exported by post-processing.

    The file is read from the standard ``_timeseries`` subfolder produced by
    the model post-processing stage. The returned table is the shared input for
    the flow diagnostic plots.
    """

    model_name = _resolve_flow_model(result).model_name
    smod_path = (
        result.setup.workspace.simulations_folder
        / model_name
        / "_postprocess"
        / "_timeseries"
        / "_simulated_timeseries.csv"
    )
    return pd.read_csv(smod_path, sep=";", index_col=0, parse_dates=True)


def plot_flow_suite(result, options: DisplayOptions) -> None:
    """Run all enabled flow figures for one completed simulation result.

    This suite is the entry point for flow-related post-processing displays.
    It resolves the standard output folder, loads the shared time-series inputs,
    and then conditionally runs:
- the cross section figure;
- the streamflow comparison figure;
- the piezometry figure.

    Each figure is guarded by its own flag in ``options.flow``.
    """

    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    model_name = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, model_name)
    base_raster = resolve_flow_base_raster(flow_model, result.setup.geographic)
    simulated_timeseries = _load_flow_timeseries(result)
    observed_streamflow = _load_observed_streamflow(result)

    if options.flow.is_enabled("cross_section", default=True):
        plot_cross_section(
            watershed_dem_path=base_raster,
            watertable_npy_path=(
                result.setup.workspace.simulations_folder
                / model_name
                / "_postprocess"
                / "watertable_elevation.npy"
            ),
            options=options,
            save_path=output_dir / "cross_section.png",
        )

    if options.flow.is_enabled("streamflow", default=True):
        plot_streamflow(
            observed_streamflow=observed_streamflow,
            simulated_timeseries=simulated_timeseries,
            model_label=model_name.upper(),
            options=options,
            save_path=output_dir / "streamflow.png",
        )

    if options.flow.is_enabled("piezometry", default=True):
        plot_piezometry(
            simulated_timeseries=simulated_timeseries,
            model_label=model_name.upper(),
            options=options,
            save_path=output_dir / "piezometry.png",
        )


def plot_particles_suite(result, options: DisplayOptions) -> None:
    """Run all enabled particle-tracking outputs for one simulation result."""

    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    model_name = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, model_name)
    particles_dir = (
        result.setup.workspace.simulations_folder
        / model_name
        / "_postprocess"
        / "_particles"
    )

    if not options.particles.is_enabled("pathlines", default=False):
        return

    pathlines_shp = particles_dir / "pathlines_weighted.shp"
    endpoints_shp = particles_dir / "starting_weighted.shp"
    plot_pathlines(
        pathlines_shp=pathlines_shp,
        endpoints_shp=endpoints_shp,
        watershed_shp=result.setup.geographic.watershed_shp,
        dem_raster=resolve_flow_base_raster(flow_model, result.setup.geographic),
        options=options,
        save_path=output_dir / "pathlines.png",
    )


def plot_transport_suite(result, options: DisplayOptions) -> None:
    """Run transport concentration exports and derived animations.

    This suite manages the transport-specific visualization workflow:
- generate concentration frames from the transport outputs;
- optionally assemble those frames into a GIF;
- optionally build an HTML slider animation for browser viewing.

    Frame generation is shared across all derived outputs so the expensive
    concentration rendering work is done only once per run.
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

    model_name = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, model_name) / "transport"
    save_frame_files = options.save or run_gif or run_web_animation
    show_last_frame = run_concentration and options.show

    # Frame generation is shared by the static images, GIF, and HTML slider.
    frame_paths = plot_concentration_frames(
        model_transport=transport_model,
        model_modflow=flow_model,
        geographic=result.setup.geographic,
        hydrography=result.loaded_data.hydrography,
        recharge_series=result.loaded_data.climatic.recharge,
        base_raster_path=resolve_flow_base_raster(flow_model, result.setup.geographic),
        output_dir=output_dir,
        prefix="concentration",
        dpi=options.dpi,
        save_frames=save_frame_files,
        show_last_frame=show_last_frame,
    )

    if run_gif:
        build_concentration_gif(
            frame_paths=frame_paths,
            gif_path=output_dir / "concentration.gif",
        )

    if run_web_animation:
        html_path = output_dir / "concentration_slider.html" if options.save else None
        plot_web_animation(
            frame_paths=frame_paths,
            html_path=html_path,
            show_in_browser=options.show,
        )
