"""Matplotlib figures used by the flow display suite.

The functions in this module create the compact diagnostic figures typically
used to inspect a completed groundwater flow run:
- a terrain / water-table cross section;
- a comparison between observed and simulated discharge;
- a piezometry view relating water-table depth to recharge.

Each function is intentionally focused on one figure so that orchestration code
can enable or disable them independently.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from hydromodpy.display.common import finalize_figure
from hydromodpy.display.options import DisplayOptions


def plot_cross_section(
    *,
    watershed_dem_path: Path,
    watertable_npy_path: Path,
    options: DisplayOptions,
    save_path: Path | None = None,
    x_index: int | None = None,
) -> None:
    """Plot a vertical cross section from DEM and water-table rasters.

    This function builds a simple pedagogical section view of the simulated
    groundwater state:
- the DEM provides the land surface elevation;
- the water-table array provides the simulated hydraulic surface;
- ``x_index`` selects which raster column is sampled.

    After masking nodata values, the function draws filled areas and lines to
    show the relative position of the surface, saturated zone, and lower base.
    """

    watertable = np.load(watertable_npy_path, allow_pickle=True).item()
    with rasterio.open(watershed_dem_path) as dem_src:
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

    x = np.arange(dem.shape[0], dtype=float) * row_spacing
    dem_section = dem[:, x_index]
    wt_section = wt[:, x_index]
    valid_values = np.concatenate([dem_section, wt_section])
    valid_values = valid_values[np.isfinite(valid_values)]
    if valid_values.size == 0:
        base_level = 0.0
        top_level = 1.0
    else:
        base_level = float(np.nanmin(valid_values) - 5.0)
        top_level = float(np.nanmax(valid_values) + 5.0)

    fig, ax = plt.subplots(figsize=(6, 4), dpi=options.dpi)
    ax.fill_between(x, base_level, wt_section, color="dodgerblue", alpha=0.5, lw=0)
    ax.plot(x, wt_section, color="navy", lw=1.5)
    ax.plot(x, dem_section, color="saddlebrown", lw=1.5)
    ax.fill_between(x, wt_section, dem_section, color="saddlebrown", alpha=0.5, lw=0)
    ax.fill_between(x, base_level, dem_section, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x, np.full_like(x, base_level), color="dimgray", lw=1.0)
    ax.set_xlim(float(x[0]), float(x[-1]) if len(x) else 0.0)
    ax.set_ylim(base_level, top_level)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=save_path)


def plot_streamflow(
    *,
    observed_streamflow: pd.DataFrame,
    simulated_timeseries: pd.DataFrame,
    model_label: str,
    options: DisplayOptions,
    save_path: Path | None = None,
    factor: int = 30,
) -> None:
    """Plot observed discharge against simulated outflow and recharge.

    The purpose of this figure is to compare what the model produces with what
    is measured at the outlet:
- the observed series is plotted as the reference signal;
- the simulated outlet flux is reconstructed from drain flow and runoff;
- recharge is added as contextual forcing on the same timeline.

    The helper applies the project plotting unit conversion used throughout
    HydroModPy example diagnostics.
    """

    # Convert model fluxes to the plotting unit used by the project diagnostics.
    rmod = simulated_timeseries["recharge"] * factor * 1000
    qmod = (simulated_timeseries["outflow_drain"] + simulated_timeseries["runoff"]) * factor * 1000

    fig, ax = plt.subplots(figsize=(12, 3.5), dpi=options.dpi)
    ax.plot(observed_streamflow, color="k", lw=2, label="Observed")
    ax.plot(qmod, color="red", lw=2, label="Simulated: outflow")
    ax.plot(rmod, color="dodgerblue", lw=2, label="Recharge")
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(pd.to_datetime("2002"), pd.to_datetime("2005"))
    ax.set_xlabel("Date")
    ax.set_ylabel("Q / A [mm/month]")
    ax.set_ylim(-5, 100)
    ax.legend(loc="upper left")
    ax.set_title(model_label, fontsize=10)
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=save_path)


def plot_piezometry(
    *,
    simulated_timeseries: pd.DataFrame,
    model_label: str,
    options: DisplayOptions,
    save_path: Path | None = None,
    factor: int = 30,
) -> None:
    """Plot simulated water-table depth together with recharge forcing.

    This figure helps relate aquifer response to climatic forcing:
- the main axis shows simulated water-table depth over time;
- the secondary axis shows recharge as bars over the same period.

    The recharge axis is mirrored so the visual reading remains natural for the
    hydrogeology convention used in the rest of the project.
    """

    rmod = simulated_timeseries["recharge"] * factor * 1000
    watertable_depth = simulated_timeseries["watertable_depth"]

    fig, ax = plt.subplots(figsize=(12, 3.5), dpi=options.dpi)
    ax.plot(watertable_depth, marker="o", color="red", lw=2, label="Simulated: watertable")
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(pd.to_datetime("2000"), pd.to_datetime("2005"))
    ax.set_xlabel("Date")
    ax.set_ylabel("WT depth [m]")
    ax.invert_yaxis()
    ax.legend(loc="upper left")
    ax.set_title(model_label, fontsize=10)

    # Overlay recharge on a mirrored secondary axis for quick visual comparison.
    axb = ax.twinx()
    axb.bar(rmod.index, rmod, color="dodgerblue", width=10, edgecolor="None", alpha=1, label="Recharge")
    axb.set_ylim(0, 100)
    axb.invert_yaxis()
    axb.legend(loc="upper right")

    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=save_path)
