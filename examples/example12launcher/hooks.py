# -*- coding: utf-8 -*-
"""
Hooks for example12launcher.

Each function named ``on_before_<phase>`` / ``on_after_<phase>`` is called
automatically by the launcher around the corresponding phase.  They receive a
single :class:`~launchers.RunResult` argument and return ``None``.

This file contains the study-specific logic extracted from ``examples/example12/
example12.py``.  The generic boilerplate (workspace, domain, solvers, …) lives
in the launcher phases and is not repeated here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from launchers import RunResult
from hydromodpy.display import (
    display_options_from_raw_toml,
    plot_flow_suite,
    plot_particles_suite,
    plot_transport_suite,
)
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

# ── on_after_data ─────────────────────────────────────────────────────────────

def on_after_data(result: RunResult) -> None:
    """Load SAFRAN-ISBA reanalysis, hydrography, intermittency and hydrometry."""
    from hydromodpy.watershed import Hydrography, Intermittency, Subbasin
    from hydromodpy.data_managers.hydrometry.station_set import StationSet

    ws        = result.workspace
    data_path = result.cfg.workspace.data_path
    geo       = result.geographic

    # ── Hydrography (Naizin-specific stream file) ─────────────────────────
    result.hydrography = Hydrography(
        out_path=ws.catch_folder,
        types_obs=["botopage2024_naizin_streams_perennial-intermittent"],
        fields_obs=["FID"],
        geographic=geo,
        hydro_path=data_path,
        streams_file=None,
    )

    # ── Intermittency ────────────────────────────────────────────────────
    result.intermittency = Intermittency(
        out_path=ws.catch_folder,
        intermittency_path=data_path,
        file_name="regional onde stations.shp",
        geographic=geo,
    )

    # ── Hydrometry stations ──────────────────────────────────────────────
    hydro_section = result.raw_toml.get("hydrometry_stations", {})
    hydro_cfg = {
        "hydrometry": {k: v for k, v in hydro_section.items()
                       if k not in ["source", "selection", "output"]},
        "source":     hydro_section.get("source", {}),
        "selection":  hydro_section.get("selection", {}),
        "output":     hydro_section.get("output", {}),
    }
    output_path = hydro_cfg["output"].get("path")
    if output_path:
        p = Path(str(output_path)).expanduser()
        if not p.is_absolute():
            hydro_cfg["output"]["path"] = str(
                (result.config_path.parent / p).resolve()
            )
    if hydro_cfg["selection"].get("mode", "mask") == "mask":
        hydro_cfg["selection"]["mask_path"] = geo.watershed_shp
    try:
        result.hydrometry = StationSet.from_config(hydro_cfg)
    except ValueError as exc:
        print(f"Warning: Hydrometry loading failed – {exc}")
        result.hydrometry = None

    # ── SAFRAN-ISBA reanalysis ────────────────────────────────────────────
    result.climatic.update_recharge_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )
    result.climatic.update_runoff_reanalysis(
        path_file=data_path / "_climate_REANALYSIS.csv",
        clim_mod="REA",
        clim_sce="historic",
        first_year=2003,
        last_year=2003,
        time_step="ME",
        sim_state="transient",
    )


# ── on_before_flow ────────────────────────────────────────────────────────────

def on_before_flow(result: RunResult) -> None:
    """Build synthetic recharge, set hydraulic parameters and model name."""

    # ── Synthetic monthly recharge ────────────────────────────────────────
    R_raw   = result.climatic.recharge
    R_synth = R_raw[(R_raw.index.year >= 2003) & (R_raw.index.year <= 2003)] * 0
    R_synth[R_synth.index.month.isin([3, 4, 5, 6, 8, 9, 10])] =  0.0
    R_synth[R_synth.index.month.isin([1, 2, 11, 12])]          =  2.0   # mm/day
    R_synth[R_synth.index.month.isin([7])]                      = -1.0   # → EVT
    R_synth.index = pd.to_datetime(R_synth.index)

    rec = R_synth / 1000        # mm/day → m/day
    run = rec * 0.1

    result.climatic.update_recharge(rec, sim_state=result.flow.flow_regime)
    result.climatic.update_runoff(run,   sim_state=result.flow.flow_regime)

    # ── Hydraulic parameters ─────────────────────────────────────────────
    alpha  = 15                       # characteristic depth [m]
    K0     = 5e-5 * 24 * 3600        # [m/day]
    Sy0    = 2 / 100

    # ── Model name ───────────────────────────────────────────────────────
    vers       = "TRANS1"
    model_name = f"{vers}_K{K0/24/3600:.1e}_a{alpha:.1f}_Sy{Sy0*100:.1f}"
    result.settings.update_model_name(model_name)
    result.settings.update_box_model(box=True)
    result.settings.update_sink_fill(sink_fill=False)
    result.settings.update_check_model(
        plot_cross=True, check_grid=True, cross_ylim=[0, 200]
    )

    # ── Inject recharge into Flow ─────────────────────────────────────────
    rech_cfg = result.flow.sinks_sources.get("recharge")
    first_clim = rech_cfg.first_clim if rech_cfg is not None else "mean"
    result.climatic.update_first_clim(first_clim)

    negative_to_evt = rech_cfg.negative_to_evt if rech_cfg is not None else True
    result.flow.set_recharge(FlowRechargeConfig(
        values=result.climatic.recharge,
        first_clim=result.climatic.first_clim,
        negative_to_evt=negative_to_evt,
    ))


# ── on_after_flow ─────────────────────────────────────────────────────────────

def on_after_flow(result: RunResult) -> None:
    """Timeseries, MatchingStreams, cross-section and streamflow plots."""
    from hydromodpy.modeling import timeseries
    from hydromodpy.calibration.calibration_legacy.matching_stream import MatchingStreams

    geo           = result.geographic
    ws            = result.workspace
    model_modflow = result.model_modflow
    model_name    = model_modflow.model_name

    # ── Timeseries (flow only) ────────────────────────────────────────────
    timeseries.Timeseries(
        geo,
        model_modflow=model_modflow,
        runoff=result.climatic.runoff,
        model_modpath=None,
        model_mt3dms=None,
        datetime_format=True,
        subbasin_results=True,
        intermittency_weekly=False,
        intermittency_monthly=True,
        intermittency_yearly=False,
    )

    # ── MatchingStreams ────────────────────────────────────────────────────
    MatchingStreams(
        geo, result.hydrography, ws,
        iteration_label=model_name,
        from_calib=False,
    )

    display_options = display_options_from_raw_toml(result.raw_toml)
    plot_flow_suite(result, display_options)


# ── on_before_particles ───────────────────────────────────────────────────────

def on_before_particles(result: RunResult) -> None:
    """Clip seepage raster and configure particle injection zone."""
    import whitebox

    ws         = result.workspace
    model_name = result.model_modflow.model_name
    sim_folder = ws.simulations_folder / model_name

    tif_seep      = sim_folder / "_postprocess/_rasters/seepage_areas_t(0).tif"
    tif_seep_clip = sim_folder / "_postprocess/_rasters/seepage_areas_t(0)_clip.tif"

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False
    wbt.clip_raster_to_polygon(
        str(tif_seep),
        str(ws.stable_folder / "geographic" / "watershed.shp"),
        str(tif_seep_clip),
        maintain_dimensions=True,
    )

    particle_params = result.cfg.transport.particle.parameters.model_dump()
    if particle_params.get("zone_partic") == "seepage_clip":
        particle_params["zone_partic"] = str(tif_seep_clip)
    result.transport.particle.set_parameters(particle_params)


# ── on_before_transport ───────────────────────────────────────────────────────

# on_after_particles
def on_after_particles(result: RunResult) -> None:
    """Render optional particle visualizations."""
    display_options = display_options_from_raw_toml(result.raw_toml)
    plot_particles_suite(result, display_options)


# on_before_transport
def on_before_transport(result: RunResult) -> None:
    """Set NO3 initial/input concentrations and first-order decay rate."""
    from hydromodpy.solver.modflow_nwt import Modflow

    mf   = result.model_modflow
    nper = mf.nper
    if isinstance(mf, Modflow):
        nlay, nrow, ncol = mf.mf.nlay, mf.mf.nrow, mf.mf.ncol
    else:
        nlay, nrow, ncol = mf.nlay, mf.nrow, mf.ncol

    sconc_init  = np.ones((nlay, nrow, ncol)) * (100 / 1000)   # 100 mg/L → kg/m3
    sconc_input = {i: np.ones((nrow, ncol)) * (50 / 1000)
                   for i in range(1, nper)}                     # skip SP0
    rate_decay  = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))

    result.transport.conc.set_parameters(
        **result.cfg.transport.conc.parameters.model_dump()
    )
    result.transport.conc.set_parameters(
        spc_name="NO3",
        sconc_init=sconc_init,
        sconc_input=sconc_input,
        rate_decay=rate_decay,
    )


# ── on_after_transport ────────────────────────────────────────────────────────

def on_after_transport(result: RunResult) -> None:
    """Generate concentration GIF and Plotly slider (from example12 lines 1293-1407)."""
    # Full timeseries with all models
    from hydromodpy.modeling import timeseries

    scenario = "s1"
    timeseries.Timeseries(
        result.geographic,
        model_modflow=result.model_modflow,
        runoff=result.climatic.runoff,
        model_modpath=result.model_modpath,
        model_mt3dms=result.model_transport,
        suffix_name=scenario,
        datetime_format=True,
        subbasin_results=True,
        intermittency_weekly=False,
        intermittency_monthly=True,
        residence_times=True,
        concentration_seepage=True,
        mass_accumulated=True,
    )
    display_options = display_options_from_raw_toml(result.raw_toml)
    plot_transport_suite(result, display_options)
