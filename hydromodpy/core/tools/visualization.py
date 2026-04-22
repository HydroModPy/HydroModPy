"""
Visualization utilities for HydroModPy examples.

Provides generalized plotting functions for consistent visualization across examples:
- create_watershed_plot(): Plot watershed information
- create_map_plot(): Plot water table depth and seepage areas
- create_crosssection_plot(): Plot water table cross-section
- create_timeseries_plot(): Plot timeseries with dual axes
"""

import logging

import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio.plot

logger = logging.getLogger(__name__)


def create_watershed_plot(dem_path, BV, model_name, visualization_watershed, visualization_results):
    """
    Create watershed information plot.

    Displays general watershed info, DEM, and grid using HydroModPy visualization modules.

    Parameters:
    -----------
    dem_path : str
        Path to DEM raster file
    BV : Watershed object
        HydroModPy Watershed object with geographic data
    model_name : str
        Name of the model/simulation
    visualization_watershed : module
        Legacy watershed-visualisation module (removed in P08).
    visualization_results : module
        Legacy results-visualisation module (removed in P08).

    Returns:
    --------
    None (displays plots)
    """
    logger.info("PLOT: WATERSHED INFO")
    visualization_watershed.watershed_local(dem_path, BV)
    visu = visualization_results.Visualization(BV, model_name)
    visu.visual2D(object_list=["map", "grid"], color_scale=[(None, None), (None, None)], lines=None)
    logger.info("Watershed plot created")


def create_map_plot(
    wtd_data,
    wtd_rio,
    seep_data,
    seep_rio,
    sim_contour,
    sim_pathlines,
    title="SIMULATED: time 1/12",
    figsize=(8, 5),
    dpi=300,
    vline_pos=None,
    vline_width=None,
    pixel_res=75,
):
    """
    Create water table depth and seepage map plot.

    Overlays water table depth (color map), seepage areas (black pixels),
    watershed boundary, and particle pathlines.

    Parameters:
    -----------
    wtd_data : array
        Water table depth raster data
    wtd_rio : rasterio object
        Water table depth raster object (for coordinate transforms)
    seep_data : masked array
        Seepage areas masked array (0 = masked/no seepage)
    seep_rio : rasterio object
        Seepage areas rasterio object
    sim_contour : GeoDataFrame
        Watershed contour polygon
    sim_pathlines : GeoDataFrame
        Particle pathlines geometry
    title : str
        Plot title (default: 'SIMULATED: time 1/12')
    figsize : tuple
        Figure size in inches (default: (8, 5))
    dpi : int
        Resolution in dots per inch (default: 300)
    vline_pos : float or None
        Vertical line position in data coordinates. If None, calculated from vline_width
    vline_width : int or None
        Column index for vertical line position (multiplied by pixel_res).
        If None, uses middle of data (auto-detect). Default None = auto.
    pixel_res : float
        Pixel resolution in meters (default: 75)

    Returns:
    --------
    tuple : (fig, ax) matplotlib figure and axes objects

    Examples:
    ---------
    >>> fig, ax = create_map_plot(
    ...     wtd_data,
    ...     wtd_rio,
    ...     seep_data,
    ...     seep_rio,
    ...     sim_contour,
    ...     sim_pathlines,
    ...     title="Water Table Depth",
    ... )
    >>> # Auto-detect vline_width (no parameters needed!)
    >>> fig, ax = create_map_plot(
    ...     wtd_data, wtd_rio, seep_data, seep_rio, sim_contour, sim_pathlines
    ... )
    """
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)

    # Plot water table depth
    sim_wtd = rasterio.plot.show(
        wtd_data, ax=ax, transform=wtd_rio.transform, cmap="jet", alpha=0.5, zorder=0, aspect="auto"
    )

    # Plot seepage areas
    rasterio.plot.show(
        seep_data,
        ax=ax,
        transform=seep_rio.transform,
        cmap=mpl.colors.ListedColormap(["k"]),
        alpha=1,
        zorder=1,
        aspect="auto",
    )

    # Plot watershed boundary and pathlines
    sim_contour.plot(ax=ax, lw=3, ec="k", fc="None")
    sim_pathlines.plot(ax=ax, color="k")

    ax.set_title(title)

    # Auto-detect vline_width if not provided (use middle of data)
    if vline_width is None:
        vline_width = wtd_data.shape[1] // 2

    # Add vertical line
    if vline_pos is None:
        vline_pos = ax.get_xlim()[0] + (vline_width * pixel_res)
    ax.axvline(x=vline_pos, color="k", ls="--", lw=3)

    fig.suptitle("Seepage fed by pathlines and map of water table depth [m]", y=1.02, fontsize=12)
    fig.tight_layout()

    logger.info("Map plot created")
    return fig, ax


def create_crosssection_plot(
    wte_data,
    dem_data,
    wte_col=None,
    title="SIMULATED: time 1/12",
    figsize=(7, 5),
    dpi=300,
    xlim=None,
    ylim=None,
):
    """
    Create water table cross-section plot.

    Extracts a vertical slice through the water table elevation and topography,
    showing the position of the water table within the subsurface.

    Automatically detects optimal column and axis limits if not specified.

    Parameters:
    -----------
    wte_data : array
        Water table elevation 2D array (rows, columns)
    dem_data : array
        DEM topography 2D array (same shape as wte_data)
    wte_col : int or None
        Column index for cross-section slice. If None, uses middle of data (auto-detect).
        Default None = wte_data.shape[1] // 2
    title : str
        Plot title (default: 'SIMULATED: time 1/12')
    figsize : tuple
        Figure size in inches (default: (7, 5))
    dpi : int
        Resolution in dots per inch (default: 300)
    xlim : tuple or None
        X-axis limits (rows). If None, auto-detect from data shape.
        Default None = (0, wte_data.shape[0])
    ylim : tuple or None
        Y-axis limits (elevation). If None, auto-detect from data range with 10m buffer.
        Default None = (nanmin(dem_data), nanmax(dem_data) + 10)

    Returns:
    --------
    tuple : (fig, ax) matplotlib figure and axes objects

    Examples:
    ---------
    >>> # Auto-detect everything
    >>> fig, ax = create_crosssection_plot(wte_data, dem_data)

    >>> # Custom column with auto xlim/ylim
    >>> fig, ax = create_crosssection_plot(wte_data, dem_data, wte_col=30)

    >>> # Full control
    >>> fig, ax = create_crosssection_plot(
    ...     wte_data, dem_data, wte_col=28, xlim=(0, 30), ylim=(40, 150)
    ... )
    """
    # Auto-detect wte_col if not provided (use middle of data)
    if wte_col is None:
        wte_col = wte_data.shape[1] // 2

    # Auto-detect xlim if not provided (full row range)
    if xlim is None:
        xlim = (0, wte_data.shape[0])

    # Auto-detect ylim if not provided (elevation range with 10m buffer)
    if ylim is None:
        dem_min = np.nanmin(dem_data)
        dem_max = np.nanmax(dem_data)
        ylim = (dem_min, dem_max + 10)

    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)

    # Extract cross-section data
    x_wte = np.arange(0, wte_data.shape[0], 1)
    y_wte = wte_data[:, wte_col : wte_col + 1]
    y_wte = np.concatenate(y_wte, axis=0)

    x_dem = np.arange(0, dem_data.shape[0], 1)
    y_dem = dem_data[:, wte_col : wte_col + 1]
    y_dem = np.concatenate(y_dem, axis=0)

    # Plot water table
    ax.fill_between(x_wte, x_wte * 0, y_wte, lw=0, alpha=0.3, color="dodgerblue")
    ax.plot(x_wte, y_wte, lw=3, color="blue", label="Water table")

    # Plot topography
    ax.fill_between(x_dem, y_wte, y_dem, lw=0, alpha=0.3, color="saddlebrown")
    ax.plot(x_dem, y_dem, lw=3, color="saddlebrown", label="Topography")

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.legend(prop={"size": 12})
    ax.set_xlabel("X pixels [75 m resolution]")
    ax.set_ylabel("Elevation [m.a.s.l]")
    ax.set_title(title)

    fig.suptitle(
        "Cross-section of water table elevation [m] at X=152737 crossing 2 pumping wells",
        y=1.02,
        fontsize=12,
    )
    fig.tight_layout()

    logger.info("Cross-section plot created")
    return fig, ax


def create_timeseries_plot(
    timeseries, well_1_fluxes, well_2_fluxes, figsize=(8, 5), dpi=300, title="SIMULATED: time 1/12"
):
    """
    Create timeseries plot with dual axes.

    Left axis: Recharge and outflow discharge
    Right axis: Combined well pumping flux

    Uses step plot for flows (cumulative values) and bar plot for pumping rates.

    Parameters:
    -----------
    timeseries : DataFrame
        Timeseries data with columns:
        - 'recharge': recharge flux [mm/d or similar]
        - 'outflow_drain': outlet discharge flux [mm/d or similar]
    well_1_fluxes : Series
        Well 1 pumping flux timeseries
    well_2_fluxes : Series
        Well 2 pumping flux timeseries
    figsize : tuple
        Figure size in inches (default: (8, 5))
    dpi : int
        Resolution in dots per inch (default: 300)
    title : str
        Plot title (default: 'SIMULATED: time 1/12')

    Returns:
    --------
    tuple : (fig, ax) matplotlib figure and axes objects

    Examples:
    ---------
    >>> fig, ax = create_timeseries_plot(
    ...     timeseries, well_1_fluxes, well_2_fluxes, figsize=(10, 6), title="Year 2017"
    ... )
    """
    # Prepare well flux data
    well_1_plot = well_1_fluxes.copy()
    well_1_plot.index = timeseries.index
    well_2_plot = well_2_fluxes.copy()
    well_2_plot.index = timeseries.index
    well_all_plot = well_1_plot + well_2_plot

    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
    axb = ax.twinx()

    # Plot recharge and outflow on left axis
    ax.step(
        timeseries.index,
        timeseries["recharge"] * 30 * 1000,
        lw=8,
        color="dodgerblue",
        label="Recharge total",
        where="pre",
        clip_on=False,
    )
    ax.step(
        timeseries.index,
        timeseries["outflow_drain"] * 30 * 1000,
        lw=5,
        color="red",
        alpha=1,
        label="Outflow at outlet",
        where="pre",
        clip_on=False,
    )

    ax.set_xlim(pd.to_datetime("2017-01"), pd.to_datetime("2018-01"))
    ax.set_ylabel("Output flow results [mm/month]")
    ax.set_ylim(0, 70)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%m"))
    ax.legend(prop={"size": 12})

    # Plot well pumping on right axis
    axb.bar(
        timeseries.index,
        well_all_plot,
        clip_on=False,
        width=5,
        lw=0,
        color="darkorange",
        label="Water from wells",
    )
    axb.set_ylabel("Sum of pumping in wells [L$^3$/T]", rotation=270, labelpad=25)
    axb.legend(prop={"size": 12}, loc="lower left", facecolor="white")

    ax.set_title(title)
    fig.suptitle(
        "Date [Year 2017: monthly stress-period (12) with daily time step length (335 in total)]",
        y=1.02,
        fontsize=12,
    )
    fig.tight_layout()

    logger.info("Timeseries plot created")
    return fig, ax
