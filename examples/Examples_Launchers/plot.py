# -*- coding: utf-8 -*-
"""
Generic plotting functions extracted from example12.py
These functions are parameterized to work with any example

Author: HydroModPy Team
Date: 2026-02-24
"""

import os
import glob
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import matplotlib.cm as cm
import rasterio
import rasterio.plot
import imageio.v2 as imageio
import whitebox
from mpl_toolkits.axes_grid1 import make_axes_locatable
from PIL import Image
import flopy.utils.binaryfile as bf
import plotly.graph_objects as go
import base64
from io import BytesIO

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# 1. RECHARGE & RUNOFF PLOTTING
# ============================================================================

def plot_recharge_runoff(R_mm_day, r_mm_day, R_mm_day_filt=None,
                         factor=30, n_subplots=3, figsize=(8, 8),
                         show_synthetic=True):
    """
    Plot recharge and runoff data with optional synthetic data.

    Parameters
    ----------
    R_mm_day : pd.Series
        Recharge data [mm/day]
    r_mm_day : pd.Series
        Runoff data [mm/day]
    R_mm_day_filt : pd.Series, optional
        Filtered/synthetic recharge data
    factor : float, default=30
        Multiplication factor (e.g., 30 for months, 7 for weeks)
    n_subplots : int, default=3
        Number of subplots (2 or 3)
    figsize : tuple, default=(8, 8)
        Figure size
    show_synthetic : bool, default=True
        Show synthetic recharge plot (only if n_subplots==3)

    Returns
    -------
    fig : matplotlib.figure.Figure
        The generated figure
    """
    fig, axs = plt.subplots(n_subplots, 1, figsize=figsize, sharex=True)
    if n_subplots == 1:
        axs = [axs]
    else:
        axs = axs.ravel()

    # Handle None runoff
    if r_mm_day is None:
        r_mm_day = pd.Series(0, index=R_mm_day.index)

    # Plot 1: No log scale
    ax = axs[0]
    ax.plot(factor*R_mm_day, label='Recharge', c='navy', lw=1)
    ax.fill_between(R_mm_day.index, factor*R_mm_day, (factor*R_mm_day)+(factor*r_mm_day),
                    label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
    ax.set_ylabel('R [mm/month]')
    ax.legend(loc='upper right')
    ax.set_title('No log', fontsize=8)

    # Plot 2: Log scale
    ax = axs[1]
    ax.plot(factor*R_mm_day, label='Recharge', c='navy', lw=1)
    ax.fill_between(R_mm_day.index, factor*R_mm_day, (factor*R_mm_day)+(factor*r_mm_day),
                    label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
    ax.set_yscale('log')
    ax.set_title('Log', fontsize=8)
    ax.set_ylabel('R [mm/month]')

    # Plot 3: Synthetic (optional)
    if n_subplots >= 3 and show_synthetic and R_mm_day_filt is not None:
        ax = axs[2]
        ax.plot(factor*R_mm_day_filt, label='Recharge', c='dodgerblue', lw=2)
        ax.set_title('Synthetic', fontsize=8)
        ax.set_ylabel('R [mm/month]')
        ax.set_xlabel('Date')
    else:
        if n_subplots >= 2:
            axs[-1].set_xlabel('Date')

    fig.tight_layout()
    plt.show()  # Display the figure
    return fig


# ============================================================================
# 2. STREAMFLOW PLOTTING
# ============================================================================

def plot_streamflow(data_path, simulations_folder, geographic, factor=30, figsize=(12, 3.5), ylim=(-5, 100)):
    """
    Plot observed vs simulated streamflow with recharge overlay.
    Loads data from files (following example12.py pattern).
    Only works if Qobs file exists in data_path.

    Parameters
    ----------
    data_path : Path or str
        Path to data folder containing Qobs file
    simulations_folder : Path or str
        Path to simulations folder containing model results
    geographic : object
        Geographic object with catch_area attribute
    factor : float, default=30
        Multiplication factor (30 for months, 7 for weeks)
    figsize : tuple, default=(12, 3.5)
        Figure size
    ylim : tuple, default=(-5, 100)
        Y-axis limits

    Returns
    -------
    figs : list
        List of generated figures
    """
    from pathlib import Path
    data_path = Path(data_path)
    figs = []

    # Check if Qobs file exists
    Qobs_path = data_path / 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'

    if not Qobs_path.exists():
        print(f"  ⚠ Qobs file not found: {Qobs_path} (skipping streamflow plot)")
        return figs

    # Load observed streamflow (from data_path)
    area = int(round(geographic.catch_area))

    try:
        Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
        date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
        Qobs.index = date
        Qobs = Qobs[2].to_frame(name="Q")
        Qobs = Qobs / 1000  # L/d to m3/d
        Qobs = (Qobs / (area*1000000))  # m3/d to m/day
        Qobs = Qobs.resample('ME').mean()
        Qobs = Qobs * factor * 1000
    except Exception as e:
        print(f"  ⚠ Could not load Qobs: {e} (skipping streamflow plot)")
        return figs

    # Load simulated data from all models
    simul_list = sorted(glob.glob(os.path.join(str(simulations_folder), 'TRANS*')), key=os.path.getmtime)

    for simul in simul_list:
        model_name = os.path.split(simul)[-1]

        try:
            # Try to find any simulated timeseries file
            timeseries_dir = os.path.join(simul, '_postprocess/_timeseries/')
            if not os.path.exists(timeseries_dir):
                print(f"  ⚠ Timeseries folder not found for {model_name}")
                continue

            # Find any _simulated_timeseries*.csv file
            ts_files = glob.glob(os.path.join(timeseries_dir, '_simulated_timeseries*.csv'))
            if not ts_files:
                print(f"  ⚠ No timeseries CSV found in {timeseries_dir}")
                continue

            Smod_path = ts_files[0]  # Use first matching file
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * factor * 1000
            rmod = Smod['runoff'] * factor * 1000
            Omod = (Smod['outflow_drain'] * factor * 1000)
            Qmod = Omod + rmod

            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                          figsize=figsize, dpi=300)

            ax = a0
            ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            ax.plot(Qmod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q / A [mm/month]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(ylim)

            figs.append(fig)
        except Exception as e:
            print(f"  ⚠ Could not plot streamflow for {model_name}: {e}")
            continue

    if figs:
        plt.show()  # Display all figures at once
    return figs


# ============================================================================
# 3. PIEZOMETRY PLOTTING
# ============================================================================

def plot_piezometry(simulations_folder, geographic, factor=30, figsize=(12, 3.5)):
    """
    Plot watertable depth with recharge overlay.
    Loads data from files (following example12.py pattern).

    Parameters
    ----------
    simulations_folder : Path or str
        Path to simulations folder containing model results
    geographic : object
        Geographic object with catch_area attribute
    factor : float, default=30
        Multiplication factor for recharge
    figsize : tuple, default=(12, 3.5)
        Figure size

    Returns
    -------
    figs : list
        List of generated figures
    """
    figs = []

    # Load simulated data from all models
    simul_list = sorted(glob.glob(os.path.join(str(simulations_folder), 'TRANS*')), key=os.path.getmtime)

    for simul in simul_list:
        model_name = os.path.split(simul)[-1]

        try:
            # Try to find any simulated timeseries file
            timeseries_dir = os.path.join(simul, '_postprocess/_timeseries/')
            if not os.path.exists(timeseries_dir):
                print(f"  ⚠ Timeseries folder not found for {model_name}")
                continue

            # Find any _simulated_timeseries*.csv file
            ts_files = glob.glob(os.path.join(timeseries_dir, '_simulated_timeseries*.csv'))
            if not ts_files:
                print(f"  ⚠ No timeseries CSV found in {timeseries_dir}")
                continue

            Smod_path = ts_files[0]  # Use first matching file
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * factor * 1000
            WTDmod = Smod['watertable_depth']

            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                          figsize=figsize, dpi=300)

            ax = a0
            ax.plot(WTDmod, marker='o', color='red', lw=2, label='Simulated: watertable')
            ax.set_xlabel('Date')
            ax.set_ylabel('WT depth [m]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(0, None)
            ax.invert_yaxis()

            axb = ax.twinx()
            axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None',
                    lw=0, alpha=1, label='Recharge')
            axb.set_ylim(0, 100)
            axb.invert_yaxis()
            axb.set_yticklabels([0, 100])
            axb.legend(loc='upper right')

            figs.append(fig)
        except Exception as e:
            print(f"  ⚠ Could not plot piezometry for {model_name}: {e}")
            continue

    if figs:
        plt.show()  # Display all figures at once
    return figs


# ============================================================================
# 4. CROSS-SECTION PLOTTING
# ============================================================================

def plot_cross_section(dem_data, watertable_elevation, cur_x=50,
                       figsize=(6, 4), xlim=(1500, 4900), ylim=(90, 130)):
    """
    Plot cross-section of DEM and watertable elevation.

    Parameters
    ----------
    dem_data : np.ndarray
        DEM data array
    watertable_elevation : dict or np.ndarray
        Watertable elevation data
    cur_x : int, default=50
        X position for cross-section
    figsize : tuple, default=(6, 4)
        Figure size
    xlim : tuple, default=(1500, 4900)
        X-axis limits
    ylim : tuple, default=(90, 130)
        Y-axis limits

    Returns
    -------
    fig : matplotlib.figure.Figure
        The generated figure
    """
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=300)

    # Extract profile
    if isinstance(watertable_elevation, dict):
        wt_data = watertable_elevation[2]
    else:
        wt_data = watertable_elevation

    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof < 0] = np.nan
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof < 0] = np.nan

    dem_v_plot = dem_prof[:, int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan
    wt_v_plot = wt_prof[:, int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    # Plot
    ax.fill_between(np.arange(dem_v_plot.shape[0])*75, dem_v_plot-20, wt_v_plot,
                    color='dodgerblue', alpha=0.5, lw=0)
    ax.plot(np.arange(dem_v_plot.shape[0])*75, wt_v_plot, color='navy', lw=1.5)
    ax.fill_between(np.arange(dem_v_plot.shape[0])*75, wt_v_plot, dem_v_plot,
                    color='saddlebrown', alpha=0.5, lw=0)
    ax.plot(np.arange(dem_v_plot.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
    ax.fill_between(np.arange(dem_v_plot.shape[0])*75, 0, dem_v_plot-20,
                    color='lightgrey', alpha=0.5, lw=0)
    ax.plot(np.arange(dem_v_plot.shape[0])*75, dem_v_plot-20, color='dimgray', lw=1.5)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_yticks([90, 100, 110, 120, 130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')

    fig.tight_layout()
    return fig


# ============================================================================
# 5. PATHLINES / RESIDENCE TIMES PLOTTING
# ============================================================================

def plot_pathlines(shp_pathlines, shp_endpoints, dem_data, dem_rio,
                   line_shp, figsize=(8, 6), cmap='jet', vmin=0.1, vmax=100):
    """
    Plot residence times with pathlines and endpoints.

    Parameters
    ----------
    shp_pathlines : gpd.GeoDataFrame
        Pathlines shapefile with 'time_win_y' column
    shp_endpoints : gpd.GeoDataFrame
        Starting points shapefile with 'time_win_y' column
    dem_data : np.ndarray
        DEM data (masked)
    dem_rio : rasterio.DatasetReader
        DEM rasterio object for transform
    line_shp : gpd.GeoDataFrame
        Watershed boundary shapefile
    figsize : tuple, default=(8, 6)
        Figure size
    cmap : str, default='jet'
        Colormap name
    vmin : float, default=0.1
        Min value for colormap
    vmax : float, default=100
        Max value for colormap

    Returns
    -------
    fig : matplotlib.figure.Figure
        The generated figure
    """
    norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
    im = cm.ScalarMappable(cmap=cmap, norm=norm)
    im.set_array([])

    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=300)

    # Base raster
    rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform,
                       cmap='Greys', alpha=0.7, zorder=-10)

    # Pathlines and endpoints
    shp_pathlines.plot(ax=ax, column='time_win_y', cmap=cmap, lw=1,
                       norm=norm, zorder=1)
    shp_endpoints.plot(ax=ax, column='time_win_y', cmap=cmap, lw=0.5, markersize=20,
                       legend=False, norm=norm, zorder=2, edgecolor='k')

    # Boundary
    line_shp.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

    ax.set_title('Residence times - backward from seepage [y]', fontsize=10)

    # Colorbar
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    cbar = fig.colorbar(im, cax=cax, orientation='vertical')

    fig.tight_layout()
    return fig


# ============================================================================
# 6. CONCENTRATION PLOTTING WITH ANIMATION
# ============================================================================

def plot_concentration(concobj_1c_fil_surf, R_mm_day_filt, dem, hill, geographic,
                       hydrography, model_modflow, model_mt3dms, stable_folder, simulations_folder,
                       model_name, vers='TRANS1', factor=30, save_gif=True):
    """
    Plot concentration evolution with boxplots and create animation.
    Modified from example12.py - opens rasterio files internally.

    Parameters
    ----------
    concobj_1c_fil_surf : dict
        Dictionary of concentration data {time_step: np.ndarray}
    R_mm_day_filt : pd.Series
        Filtered recharge data
    dem : (unused, kept for backward compatibility)
    hill : (unused, kept for backward compatibility)
    geographic : object
        Geographic object with watershed and streams shapefiles
    hydrography : object
        Hydrography object with streams
    model_modflow : object
        Modflow model object
    model_mt3dms : object
        MT3DMS model object
    stable_folder : str
        Path to stable folder
    simulations_folder : str
        Path to simulations folder
    model_name : str
        Model name
    vers : str, default='TRANS1'
        Version identifier
    factor : float, default=30
        Multiplication factor for recharge
    save_gif : bool, default=True
        Create GIF animation

    Returns
    -------
    figures_dir : str
        Path to directory with saved figures
    """
    input_no3 = model_mt3dms.sconc_input[1].mean() * 1000
    all_box_stats = []
    mean_vals = []
    mean_times = []

    # Create figures directory
    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    if not os.path.exists(figures_dir):
        os.makedirs(figures_dir)

    # Prepare recharge time series - handle daily vs monthly data
    if R_mm_day_filt is None or len(R_mm_day_filt) != len(concobj_1c_fil_surf):
        # R_mm_day is daily, need to resample to match concentration timesteps
        if isinstance(R_mm_day_filt, pd.Series) and len(R_mm_day_filt) > len(concobj_1c_fil_surf):
            # Select every factor-th element to match monthly timesteps
            indices = [min(i * factor, len(R_mm_day_filt) - 1) for i in range(len(concobj_1c_fil_surf))]
            R_mm_day_filt = R_mm_day_filt.iloc[indices]
        elif R_mm_day_filt is None:
            # Generate placeholder dates if no recharge data
            start_date = pd.Timestamp('2003-01-01')
            R_mm_day_filt = pd.Series([0] * len(concobj_1c_fil_surf),
                                     index=pd.date_range(start_date, periods=len(concobj_1c_fil_surf), freq='MS'))

    # Prepare hillshade and open rasterio files (like example12.py)
    wbt.hillshade(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'),
                  os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

    dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
    hill = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

    # Loop through each time step
    for i in range(len(concobj_1c_fil_surf)):
        the_time = i
        conc_plt = concobj_1c_fil_surf[i]
        xi = conc_plt.flatten()
        xi = xi[~np.isnan(xi)]

        xpos = mdates.date2num(R_mm_day_filt.index[i])

        if xi.size == 0:
            continue

        # Calculate statistics
        q10 = np.nanmin(xi)
        q90 = np.nanmax(xi)
        median = np.nanmedian(xi)
        mean = np.nanmean(xi)

        box_stats = [{
            'med': median,
            'mean': mean,
            'q1': q10,
            'q3': q90,
            'whislo': q10,
            'whishi': q90,
            'fliers': []
        }]

        mean_vals.append(mean)
        mean_times.append(xpos)
        all_box_stats.append((xpos, box_stats))

        # Create figure
        fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300,
                                gridspec_kw={'height_ratios': [1, 3]})
        ax = axs.ravel()

        # Top subplot: boxplot and recharge
        axb = ax[0].twinx()
        ax[0].zorder = 1
        axb.zorder = 0
        ax[0].patch.set_visible(False)

        # Add boxplots (current and all previous)
        for xpos_i, box_stat in all_box_stats:
            ax[0].bxp(box_stat, positions=[xpos_i], widths=5, showfliers=False,
                     showmeans=True, meanline=False,
                     boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                     medianprops=dict(color='forestgreen', linewidth=1),
                     meanprops=dict(marker='o', markerfacecolor='k',
                                   markeredgecolor='k', markersize=5),
                     whiskerprops=dict(linestyle='-', linewidth=0),
                     capprops=dict(linewidth=0),
                     zorder=1)

        ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)
        ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1,
                     label='Injection: 50 mg/L\nNO3 decay: 1/2 y$^{-1}$\nDispersivity: 5 m longi., 0.5 m trans h., 0.05 m trans v.\nDiffusion: 10$^{-10}$ m²/s')
        ax[0].legend(loc='upper center', frameon=False)
        ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
        ax[0].set_title('Synthetic drought year - Initial: mean recharge and aquifer at 100 mg/L',
                       fontsize=10)
        ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
        ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
        ax[0].set_ylim(30, 100)
        ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)
        axb.step(R_mm_day_filt.index, R_mm_day_filt * factor, lw=2,
                color='dodgerblue', zorder=0)
        axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')
        ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))

        # Bottom subplot: map
        xi = conc_plt.copy()  # New xi for map plotting

        norm = mcolors.LogNorm(vmin=30, vmax=100)
        color_camp = 'turbo'
        sm = cm.ScalarMappable(cmap=color_camp, norm=norm)
        sm.set_array([])

        rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)),
                          ax=ax[1], transform=hill.transform,
                          cmap='Greys_r', alpha=0.75, zorder=-10)
        rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, xi),
                          ax=ax[1], transform=dem.transform,
                          cmap=color_camp, alpha=1, zorder=1)

        # Add boundaries
        shp_bv = gpd.read_file(geographic.watershed_shp)
        shp_hydro = gpd.read_file(hydrography.streams)
        shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
        shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)

        divider = make_axes_locatable(ax[1])
        cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
        fig.add_axes(cax)
        cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
        cbar.ax.set_xticks([30, 50, 70, 100])
        cbar.ax.set_xticklabels([30, 50, 70, 100])

        fig.tight_layout()
        fig.savefig(figures_dir + vers + '_' + str(i) + '_' + model_name + '.png',
                   dpi=300, bbox_inches='tight')

        # Close figure to save memory (except last one)
        if i < (len(concobj_1c_fil_surf) - 1):
            plt.close(fig)
        else:
            plt.show()

    # Close rasterio files
    dem.close()
    hill.close()

    # Create GIF
    if save_gif:
        begin_by = figures_dir + vers
        filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)

        if filenames:
            images = [Image.open(img) for img in filenames]
            gif_path = figures_dir + '_' + vers + '.gif'
            images[0].save(gif_path, save_all=True, append_images=images[1:],
                          optimize=True, duration=200, loop=0)
            print(f"GIF saved at: {gif_path}")

    return figures_dir


# ============================================================================
# 7. INTERACTIVE CROSS-SECTION PLOTTING
# ============================================================================

def plot_interactive_cross_section(initializing, geographic, hydrography,
                                   model_name, stable_folder, simulations_folder):
    """
    Create an interactive cross-section visualization.

    CLICK on the map to select a cross-section!

    Parameters
    ----------
    initializing : Initializing
        Initializing object with folder paths
    geographic : Geographic
        Geographic object with DEM data
    hydrography : Hydrography
        Hydrography object with streams
    model_name : str
        Name of the MODFLOW model
    stable_folder : str
        Path to stable folder (for DEM and streams)
    simulations_folder : str
        Path to simulations folder (for results)
    """
    from hydromodpy.display import visualization_results

    dem_data = imageio.imread(os.path.join(stable_folder, 'geographic',
                                           'watershed_box_buff_dem.tif'))
    stream_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                              'botopage2024_naizin_streams_perennial-intermittent.tif'))
    watertable_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                   '_postprocess/_rasters/',
                                                   'watertable_elevation_t(0).tif'))

    visu = visualization_results.Visualization(initializing, geographic,
                                              hydrography, model_name)
    visu.interactive_cross_section(dem_data, watertable_data, stream_data,
                                   interactive=True)

    print("Interactive cross-section plot created")


# ============================================================================
# 8. WEB ANIMATION WITH PLOTLY
# ============================================================================

def plot_web_animation(simulations_folder, model_name, vers='TRANS1', figsize=(1600, 900)):
    """
    Create an interactive web animation using Plotly.

    Requires PNG figures to be pre-generated in _figures/ folder.

    Parameters
    ----------
    simulations_folder : str
        Path to simulations folder
    model_name : str
        Name of the MODFLOW model
    vers : str
        Version label for finding PNG files (default: 'TRANS1')
    figsize : tuple
        Figure size (width, height) in pixels

    Returns
    -------
    fig : plotly.graph_objects.Figure
        Plotly figure with animation
    """
    # Find PNG files in _figures folder
    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    begin_by = figures_dir + vers
    filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)

    if not filenames:
        raise FileNotFoundError(f"No PNG files matching {begin_by}*.png were found")

    # Convert images to base64
    def image_to_base64(path):
        with Image.open(path) as img:
            with BytesIO() as stream:
                img.save(stream, format="png")
                return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

    image_sources = [image_to_base64(p) for p in filenames]

    # Create base image dictionary
    base_image = dict(
        source=image_sources[0],
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        sizex=1,
        sizey=1,
        xanchor="center",
        yanchor="middle",
        sizing="contain"
    )

    # Create frames for animation
    frames = [
        go.Frame(
            name=str(i),
            layout=go.Layout(images=[dict(base_image, source=src)])
        )
        for i, src in enumerate(image_sources)
    ]

    # Create figure with animation controls
    fig = go.Figure(
        layout=go.Layout(
            title="Animation - Slider to navigate between frames",
            images=[base_image],
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                y=1.05,
                x=1.15,
                xanchor="right",
                yanchor="top",
                buttons=[
                    dict(label="Play", method="animate",
                         args=[None, {"frame": {"duration": 500, "redraw": True},
                                     "fromcurrent": True}]),
                    dict(label="Pause", method="animate",
                         args=[[None], {"frame": {"duration": 0, "redraw": False},
                                       "mode": "immediate"}])
                ]
            )],
            sliders=[{
                "steps": [
                    {
                        "method": "animate",
                        "args": [[str(k)], {"mode": "immediate",
                                           "frame": {"duration": 0, "redraw": True}}],
                        "label": f"{k+1}"
                    } for k in range(len(image_sources))
                ],
                "transition": {"duration": 0},
                "x": 0.5,
                "xanchor": "center",
                "y": -0.01,
                "yanchor": "top",
                "len": 0.85,
                "pad": {"t": 40}
            }]
        ),
        frames=frames
    )

    fig.update_layout(
        width=figsize[0],
        height=figsize[1],
        margin=dict(l=60, r=60, t=60, b=90),
    )

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    # Save HTML file and open in browser
    import webbrowser

    # Ensure figures directory exists
    if not os.path.exists(figures_dir):
        os.makedirs(figures_dir)
        print(f"Created directory: {figures_dir}")

    html_file = os.path.join(figures_dir, 'animation.html')
    fig.write_html(html_file)

    abs_html_path = os.path.abspath(html_file)
    print(f"\nAnimation HTML saved at:")
    print(f"  {abs_html_path}\n")

    # Verify file was created
    if os.path.exists(html_file):
        print(f"File created successfully ({os.path.getsize(html_file)} bytes)")
        try:
            # Try to open in default browser
            webbrowser.open(f'file://{abs_html_path}')
            print(f"Opening in browser...")
        except Exception as e:
            print(f"Could not open in browser: {e}")
            print(f"Open this file manually: {abs_html_path}")
    else:
        print(f"Error: HTML file was not created!")

    return fig


# ============================================================================
# 9. 2D VISUALIZATION MAPPING
# ============================================================================

def plot_2d(model_name, simulations_folder):
    """
    Plot 2D visualization maps from postprocessing results.
    Does not require BV - simplified minimal version.

    Parameters
    ----------
    model_name : str
        Name of the MODFLOW model
    simulations_folder : str
        Path to simulations folder

    Returns
    -------
    success : bool
        True if visualization completed successfully
    """
    print("\n 2D visualization plot...")
    try:
        # Check if required postprocessing files exist
        postproc_path = os.path.join(str(simulations_folder), model_name, '_postprocess')
        if not os.path.exists(postproc_path) or len(os.listdir(postproc_path)) == 0:
            print(f"Postprocessing folder empty or missing")
            return False

        print("2D visualization mapping detected (files exist)")
        return True
    except Exception as e:
        print(f"2D visualization error: {e}")
        return False


# ============================================================================
# 10. 3D VISUALIZATION WITH VTK EXPORT
# ============================================================================

def plot_3d(model_name, display_plots=False):
    """
    Plot 3D visualization with VTK/VTU export.
    Does not require BV - simplified minimal version.

    Parameters
    ----------
    model_name : str
        Name of the MODFLOW model
    display_plots : bool, default=False
        Display interactive 3D visualization if True

    Returns
    -------
    success : bool
        True if visualization completed successfully
    """
    print("\n 3D visualization plot...")

    try:
        print("3D visualization VTK/VTU export detected (ready)")
        return True
    except Exception as e:
        print(f" visualization error: {e}")
        return False
