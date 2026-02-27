# -*- coding: utf-8 -*-
"""
Plotting functions extracted DIRECTLY from example12.py
DO NOT MODIFY - These are exact copies from example12.py
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

try:
    import plotly.graph_objects as go
    import base64
    from io import BytesIO
except ImportError:
    pass

try:
    from hydromodpy.display import visualization_results, export_vtuvtk
except ImportError:
    pass

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# PLOT CROSS-SECTION - EXACT FROM example12.py lines 444-485
# ============================================================================

def plot_cross_section(geographic, stable_folder, simulations_folder, model_name):
    """Plot cross-section - EXACT from example12.py"""
    fig, ax = plt.subplots(1, 1, figsize=(6, 4), dpi=300)
    print(stable_folder)

    mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
    watertable_elevation = np.load(os.path.join(simulations_folder, model_name, '_postprocess', 'watertable_elevation.npy'), allow_pickle=True).item()

    dem_data = imageio.imread(geographic.watershed_dem)
    wt_data = watertable_elevation[2]

    xvalues = np.linspace(-1, 1, dem_data.shape[1])
    yvalues = np.linspace(-1, 1, dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues, yvalues)

    cur_x = dem_data.shape[1] / 2
    cur_x = 50

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof < 0] = np.nan
    dem_max = dem_data.max()
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof < 0] = np.nan
    dem_plot = np.ma.masked_array(dem_data, mask=(dem_data < 0))
    dem_v_plot = dem_prof[:, int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan
    wt_v_plot = wt_prof[:, int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    wt_v_fill = ax.fill_between(np.arange(xx.shape[0]) * 75, dem_v_plot - 20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
    w_prof = ax.plot(np.arange(xx.shape[0]) * 75, wt_v_plot, color='navy', lw=1.5)
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0]) * 75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
    d_prof = ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot, 'saddlebrown', lw=1.5)
    ax.fill_between(np.arange(xx.shape[0]) * 75, 0, dem_v_plot - 20, color='lightgrey', alpha=0.5, lw=0)
    ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot - 20, color='dimgray', lw=1.5)

    ax.set_xlim(1500, 4900)
    ax.set_ylim(90, 130)
    ax.set_yticks([90, 100, 110, 120, 130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')

    plt.tight_layout()
    return fig, ax


# ============================================================================
# PLOT STREAMFLOW - WITH DYNAMIC FACTOR PARAMETER
# ============================================================================

def plot_streamflow(geographic, data_path, simulations_folder, vers, factor=30):
    """Plot streamflow - with dynamic factor for different examples

    Parameters:
    -----------
    factor : int, default=30
        Scaling factor for data (30 for monthly ex12, 7 for weekly ex09)
    """
    area = int(round(geographic.catch_area))

    # Determine resampling frequency based on factor
    if factor <= 10:
        resample_freq = 'W'  # Weekly
    else:
        resample_freq = 'ME'  # Monthly

    # Try to load observed streamflow
    Qobs_path = os.path.join(data_path, 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt')
    Qobs = None
    if os.path.exists(Qobs_path):
        try:
            Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
            date = pd.to_datetime(Qobs[0] + ' ' + Qobs[1], format="%d/%m/%Y %H:%M:%S")
            Qobs.index = date
            Qobs = Qobs[2].to_frame(name="Q")
            Qobs = Qobs / 1000  # L/d to m3/d
            Qobs = (Qobs / (area * 1000000))  # m3/d to m/day
            Qobs = Qobs.resample(resample_freq).mean()
            Qobs = Qobs * factor * 1000
        except Exception as e:
            print(f"  ⚠ Warning: Could not load observed streamflow: {e}")
            Qobs = None

    simul_list = sorted(glob.glob(os.path.join(simulations_folder, vers + '*')), key=os.path.getmtime)

    for i, simul in enumerate(simul_list[:]):
        fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

        model_name = os.path.split(simul)[-1]

        # Try to load timeseries file with multiple possible names
        timeseries_dir = os.path.join(simul, '_postprocess', '_timeseries')
        possible_files = [
            '_simulated_timeseries_s1.csv',
            '_simulated_timeseries.csv',
            '_simulated_timeseries_modflow_only.csv'
        ]
        Smod = None
        for fname in possible_files:
            Smod_path = os.path.join(timeseries_dir, fname)
            if os.path.exists(Smod_path):
                try:
                    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    break
                except Exception:
                    continue

        if Smod is None:
            print(f"  ⚠ Warning: Could not find timeseries file for {model_name}, skipping...")
            plt.close(fig)
            continue

        Rmod = Smod['recharge'] * factor * 1000
        rmod = Smod['runoff'] * factor * 1000

        Omod = (Smod['outflow_drain'] * factor * 1000)
        Qmod = Omod + rmod

        ax = a0
        if Qobs is not None:
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
        ax.set_ylim(-5, 100)


# ============================================================================
# PLOT PIEZOMETRY - WITH DYNAMIC FACTOR PARAMETER
# ============================================================================

def plot_piezometry(geographic, simulations_folder, vers, factor=30):
    """Plot piezometry - with dynamic factor for different examples

    Parameters:
    -----------
    factor : int, default=30
        Scaling factor for data (30 for monthly ex12, 7 for weekly ex09)
    """
    area = int(round(geographic.catch_area))

    simul_list = sorted(glob.glob(os.path.join(simulations_folder, vers + '*')), key=os.path.getmtime)
    for i, simul in enumerate(simul_list[:]):
        model_name = os.path.split(simul)[-1]

        # Try to load timeseries file with multiple possible names
        timeseries_dir = os.path.join(simul, '_postprocess', '_timeseries')
        possible_files = [
            '_simulated_timeseries_s1.csv',
            '_simulated_timeseries.csv',
            '_simulated_timeseries_modflow_only.csv'
        ]
        Smod = None
        for fname in possible_files:
            Smod_path = os.path.join(timeseries_dir, fname)
            if os.path.exists(Smod_path):
                try:
                    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                    break
                except Exception:
                    continue

        if Smod is None:
            print(f"  ⚠ Warning: Could not find timeseries file for {model_name}, skipping...")
            continue

        Rmod = Smod['recharge'] * factor * 1000

        WTEmod = Smod['watertable_elevation']
        WTDmod = Smod['watertable_depth']

        fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

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
        axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
        axb.set_ylim(0, 100)
        axb.invert_yaxis()
        axb.set_yticklabels([0, 100])
        axb.legend(loc='upper right')


# ============================================================================
# PLOT PATHLINES - EXACT FROM example12.py lines 613-683
# ============================================================================

def plot_pathlines(geographic, stable_folder, simulations_folder, model_name):
    """Plot pathlines - EXACT from example12.py"""
    shp_pathlines = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'pathlines_weighted.shp'))
    shp_endpoints = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'starting_weighted.shp'))

    line = gpd.read_file(os.path.join(stable_folder, 'geographic', 'watershed.shp'))

    dem_rio = rasterio.open(geographic.watershed_box_buff_dem)
    dem_data = dem_rio.read(1)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)

    norm = mcolors.LogNorm(vmin=0.1, vmax=100)
    im = cm.ScalarMappable(cmap='jet', norm=norm)
    im.set_array([])

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))

    # Base raster and layers
    rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform,
                       cmap='Greys', alpha=0.7, zorder=-10)

    shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=1,
                       norm=norm, zorder=1)

    shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5, markersize=20,
                       legend=False, norm=norm, zorder=2, edgecolor='k')

    line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

    # Title
    ax.set_title('Residence times - backward from seepage [y]', fontsize=10)

    # Colorbar on the right, same height
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    cbar = fig.colorbar(im, cax=cax, orientation='vertical')

    fig.tight_layout()
    return fig, ax


# ============================================================================
# PLOT CONCENTRATION - EXACT FROM example12.py lines 851-1050
# ============================================================================

def plot_concentration(geographic, hydrography, stable_folder, simulations_folder,
                      model_name, model_modflow, model_mt3dms, R_mm_day_filt, vers='TRANS1', factor=30):
    """Plot concentration - with dynamic factor for different examples

    Parameters:
    -----------
    factor : int, default=30
        Scaling factor for data (30 for monthly ex12, 7 for weekly ex09)
    """

    input_no3 = model_mt3dms.sconc_input[1].mean() * 1000

    ucnobj = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt + '.UCN')
    concobj_1c = ucnobj.get_alldata(mflay=None)  # 4D:[time, lay, row, col]

    concobj_1c_fil = concobj_1c.copy() * 1000
    concobj_1c_fil[concobj_1c_fil >= 1e30] = np.nan
    concobj_1c_fil = concobj_1c_fil[:]

    concobj_1c_fil_surf = {}

    the_mins = []
    the_maxs = []

    for i in range((model_mt3dms.model_modflow.nper)):
        the_time = i
        seep = imageio.imread(os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif'))
        concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time + 1][0]
        concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])

        the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
        the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

    the_min = np.nanmin(the_mins)
    the_max = np.nanmax(the_maxs)

    concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

    all_box_stats = []

    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    if not os.path.exists(figures_dir):
        os.makedirs(figures_dir)

    mean_vals = []
    mean_times = []

    wbt.hillshade(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'),
                  os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

    dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
    hill = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

    for i in range(len(concobj_1c_fil_surf)):
        the_time = i

        conc_plt = concobj_1c_fil_surf[i]

        xi = conc_plt.flatten()
        xi = xi[~np.isnan(xi)]

        xpos = mdates.date2num(R_mm_day_filt.index[i])

        if xi.size == 0:
            continue

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

        fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})
        ax = axs.ravel()

        axb = ax[0].twinx()

        ax[0].zorder = 1
        axb.zorder = 0
        ax[0].patch.set_visible(False)

        for xpos, box_stat in all_box_stats:
            ax[0].bxp(box_stat, positions=[xpos], widths=5, showfliers=False,
                    showmeans=True, meanline=False,
                    boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                    medianprops=dict(color='forestgreen', linewidth=1),
                    meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5),
                    whiskerprops=dict(linestyle='-', linewidth=0),
                    capprops=dict(linewidth=0),
                    zorder=1)

        ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)

        ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1,
                    label='Injection: 50 mg/L \nNO3 decay : 1/2 y$^{-1}$ \nDispersivity: 5 m longi., 0.5 m trans h., 0.05 m trans v. \nDiffusion: 10$^{-10}$ m²/s')

        ax[0].legend(loc='upper center', frameon=False)

        ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
        ax[0].set_title('Synthetic drought year - Initial: mean recharge and aquifer at 100 mg/L', fontsize=10)
        ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
        ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
        ax[0].set_ylim(30, 100)

        ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)

        axb.step(R_mm_day_filt.index, R_mm_day_filt * factor, lw=2, color='dodgerblue', zorder=0)
        axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')

        ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))

        xi = conc_plt.copy()

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

        shp_bv = gpd.read_file(geographic.watershed_shp)
        shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)

        if hydrography is not None:
            try:
                shp_hydro = gpd.read_file(hydrography.streams)
                shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)
            except Exception as e:
                print(f"  ⚠ Warning: Could not plot hydrography: {e}")

        divider = make_axes_locatable(ax[1])
        cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
        fig.add_axes(cax)
        cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
        cbar.ax.set_xticks([30, 50, 70, 100])
        cbar.ax.set_xticklabels([30, 50, 70, 100])
        fig.tight_layout()

        fig.tight_layout()
        fig.savefig(figures_dir + vers + '_' + str(i) + '_' + model_name + '.png', dpi=300, bbox_inches='tight')

        if i < (len(concobj_1c_fil_surf) - 1):
            plt.close(fig)
        else:
            plt.show()

    # Create GIF
    vgif_name = vers
    gif_name = vgif_name + '.gif'
    begin_by = figures_dir + vgif_name
    filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)
    images = []
    for filename in filenames:
        images.append(imageio.imread(filename))

    image_paths = filenames
    images = [Image.open(img) for img in image_paths]
    images[0].save(figures_dir + '_' + gif_name, save_all=True, append_images=images[1:], optimize=True, duration=200, loop=0)

    dem.close()
    hill.close()

    return figures_dir


# ============================================================================
# PLOT 2D - EXACT FROM example12.py lines 708-735
# ============================================================================

def plot_2d(initializing, geographic, hydrography, model_name):
    """Plot 2D visualization - EXACT from example12.py"""
    try:
        if hydrography is None:
            print("  ⚠ Warning: Hydrography data not available, skipping 2D visualization")
            return
        visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
        visu.visual2D(object_list=[
            'map',
            'grid',
            'watertable',
            'watertable_depth',
            'drain_flow',
            'surface_flow',
            'pathlines',
            'residence_times'
        ],
        color_scale=[
            (None, None),
            (80, 150),
            (80, 150),
            (0, 10),
            (0, 200),
            (0, 30000),
            (0, 3),
            (0, 3),
        ],
        lines=1000)
    except Exception as e:
        print(f"  ⚠ Error in 2D visualization: {e}")


# ============================================================================
# PLOT 3D - EXACT FROM example12.py lines 737-758
# ============================================================================

def plot_3d(initializing, geographic, hydrography, model_name):
    """Plot 3D visualization - EXACT from example12.py"""
    try:
        if hydrography is None:
            print("  ⚠ Warning: Hydrography data not available, skipping 3D visualization")
            return

        # Create VTU files first (they will be generated if not present)
        export_vtuvtk.VTK(initializing, geographic, hydrography, model_name)

        # Then create visualization object and display
        visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
        visu.visual3D(interactive=True, object_list=[
            'grid',
            'watertable',
            'watertable_depth',
            'surface_flow',
            'drain_flow',
            'pathlines'
        ],
        view='south-west',
        lines=None,
        cloc=(0.7, 0.1),
        z_scale=10)
    except Exception as e:
        print(f"  ⚠ Error in 3D visualization: {e}")


# ============================================================================
# PLOT INTERACTIVE CROSS-SECTION - EXACT FROM example12.py lines 1060-1067
# ============================================================================

def plot_interactive_cross_section(initializing, geographic, hydrography,
                                   stable_folder, simulations_folder, model_name):
    """Plot interactive cross-section - EXACT from example12.py"""
    try:
        if hydrography is None:
            print("  ⚠ Warning: Hydrography data not available, skipping interactive cross-section visualization")
            return

        dem_path = os.path.join(stable_folder, 'geographic', 'watershed_box_buff_dem.tif')
        if not os.path.exists(dem_path):
            print(f"  ⚠ Warning: DEM file not found at {dem_path}, skipping interactive visualization")
            return

        dem_data = imageio.imread(dem_path)
        stream_data = imageio.imread(os.path.join(stable_folder, 'hydrography', 'botopage2024_naizin_streams_perennial-intermittent.tif'))
        watertable_data = imageio.imread(os.path.join(simulations_folder, model_name, '_postprocess', '_rasters', 'watertable_elevation_t(0).tif'))
        interactive = True
        visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
        visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)
    except Exception as e:
        print(f"  ⚠ Error in interactive cross-section visualization: {e}")


# ============================================================================
# WEB ANIMATION - EXACT FROM example12.py lines 1069-1156
# ============================================================================

def plot_web_animation(simulations_folder, vers):
    """Plot web animation - EXACT from example12.py"""
    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    begin_by = figures_dir + vers
    filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)

    def image_to_base64(path):
        with Image.open(path) as img:
            with BytesIO() as stream:
                img.save(stream, format="png")
                return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

    image_sources = [image_to_base64(p) for p in filenames]

    if not image_sources:
        raise FileNotFoundError(f"No PNG files matching {begin_by}*.png were found")

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

    frames = [
        go.Frame(
            name=str(i),
            layout=go.Layout(images=[dict(base_image, source=src)])
        )
        for i, src in enumerate(image_sources)
    ]

    fig = go.Figure(
        layout=go.Layout(
            title="Slider to navigate between images",
            images=[base_image],
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                y=1.05,
                x=1.15,
                xanchor="right",
                yanchor="top",
                buttons=[
                    dict(label="Play", method="animate", args=[None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}]),
                    dict(label="Pause", method="animate", args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}])
                ]
            )],
            sliders=[{
                "steps": [
                    {
                        "method": "animate",
                        "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}],
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
        width=1600,
        height=900,
        margin=dict(l=60, r=60, t=60, b=90)
    )

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    fig.show("browser")


import numpy as np
import imageio
import os

def plot_model_cross_section(geographic, model_folder, model_name, cur_x=50,
                             ylim=[90, 130], xlim=[1500, 4900], dx=75):
    """Génère la coupe 2D du modèle (Topographie vs Nappe)."""

    # Chemins des fichiers
    dem_path = geographic.watershed_dem
    wt_path = os.path.join(model_folder, model_name, '_postprocess', 'watertable_elevation.npy')

    if not os.path.exists(wt_path):
        print(f"Erreur: Fichier résultat non trouvé pour {model_name}")
        return

    # Chargement
    dem_data = imageio.imread(dem_path)
    watertable_elevation = np.load(wt_path, allow_pickle=True).item()
    wt_data = watertable_elevation[2] # On prend l'item 2 comme dans votre code

    # Préparation des données de profil
    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof < 0] = np.nan
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof < 0] = np.nan

    # Extraction de la colonne cur_x
    dem_v_plot = dem_prof[:, int(cur_x)]
    wt_v_plot = wt_prof[:, int(cur_x)]
    dist = np.arange(len(dem_v_plot)) * dx

    # Plot
    fig, ax = plt.subplots(1, 1, figsize=(8, 5), dpi=300)

    # Remplissages (Eau, Sol, Bedrock)
    ax.fill_between(dist, dem_v_plot-20, wt_v_plot, color='dodgerblue', alpha=0.5, label='Water')
    ax.fill_between(dist, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, label='Soil')
    ax.fill_between(dist, 0, dem_v_plot-20, color='lightgrey', alpha=0.5)

    # Lignes
    ax.plot(dist, wt_v_plot, color='navy', lw=1.5)
    ax.plot(dist, dem_v_plot, color='saddlebrown', lw=1.5)
    ax.plot(dist, dem_v_plot-20, color='dimgray', lw=1.5)

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    ax.set_title(f"Cross-section: {model_name} (x={cur_x*dx}m)")

    plt.tight_layout()
    return fig, ax

def plot_recharge_summary(R_mm_day, r_mm_day, R_mm_day_filt, title="Recharge Analysis", save_path=None):
    """Affiche la recharge et le runoff en mode linéaire, log et filtré."""
    fig, axs = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    # Conversion jour -> mois approximative (*30)
    recharge_month = 30 * R_mm_day
    total_month = 30 * (R_mm_day + r_mm_day)

    # 1. Linéaire
    axs[0].plot(recharge_month, label='Recharge', c='navy', lw=1)
    axs[0].fill_between(R_mm_day.index, recharge_month, total_month,
                        label='Recharge + Runoff', color='dodgerblue', alpha=0.8)
    axs[0].set_ylabel('R [mm/month]')
    axs[0].legend(loc='upper right')
    axs[0].set_title(f'{title} - Linear scale', fontsize=10)

    # 2. Log
    axs[1].plot(recharge_month, c='navy', lw=1)
    axs[1].fill_between(R_mm_day.index, recharge_month, total_month, color='dodgerblue', alpha=0.8)
    axs[1].set_yscale('log')
    axs[1].set_ylabel('R [mm/month]')
    axs[1].set_title('Log scale', fontsize=10)

    # 3. Filtré (SAFRAN-ISBA style)
    axs[2].plot(30 * R_mm_day_filt, label='Filtered Recharge', c='dodgerblue', lw=2)
    axs[2].set_ylabel('R [mm/month]')
    axs[2].set_title('Filtered Signal', fontsize=10)
    axs[2].set_xlabel('Date')

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=300)
    return fig, axs

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os

def plot_piezometry_recharge(model_path, model_name, xlim=['2000', '2005'], ylim_depth=None):
    """Affiche la profondeur de nappe (WTD) et la recharge sur un même graphique."""
    sim_path = os.path.join(model_path, r'_postprocess/_timeseries/_simulated_timeseries.csv')
    if not os.path.exists(sim_path):
        print(f"Fichier non trouvé : {sim_path}")
        return

    Smod = pd.read_csv(sim_path, sep=';', index_col=0, parse_dates=True)
    Rmod = Smod['recharge'] * 30 * 1000  # Conversion mm/mois
    WTDmod = Smod['watertable_depth']

    fig, ax1 = plt.subplots(1, 1, figsize=(12, 4), dpi=300)

    # Axe 1 : Profondeur de nappe
    ax1.plot(WTDmod, marker='o', markersize=3, color='red', lw=1.5, label='Simulated WT Depth')
    ax1.set_ylabel('WT depth [m]')
    ax1.set_xlabel('Date')
    ax1.set_xlim(pd.to_datetime(xlim[0]), pd.to_datetime(xlim[1]))
    if ylim_depth: ax1.set_ylim(ylim_depth)
    ax1.invert_yaxis()  # La surface est en haut (0)
    ax1.legend(loc='upper left')

    # Axe 2 : Recharge (Barres bleues)
    ax2 = ax1.twinx()
    ax2.bar(Rmod.index, Rmod, color='dodgerblue', width=15, alpha=0.6, label='Recharge')
    ax2.set_ylabel('Recharge [mm/month]')
    ax2.set_ylim(0, Rmod.max() * 3) # On laisse de la place en bas
    ax2.invert_yaxis() # Pluie qui tombe du haut
    ax2.legend(loc='upper right')

    # Formatage dates
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    plt.title(model_name.upper())
    plt.tight_layout()
    return fig, ax1

from hydromodpy.viz import visualization_results, export_vtuvtk

def run_full_visualizations2D_3D(initializing, geographic, hydrography, model_name,
                             run_2d=True, run_3d=True, export_vtk=False):
    """Exécute les modules de visualisation standard de HydromodPy."""

    # 1. Export VTK (pour Paraview)
    if export_vtk:
        print(f"Exporting VTK for {model_name}...")
        export_vtuvtk.VTK(initializing, geographic, hydrography, model_name)

    visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)

    # 2. Visualisation 2D
    if run_2d:
        print(f"Generating 2D Visuals for {model_name}...")
        obj_list = ['map', 'grid', 'watertable', 'watertable_depth',
                    'drain_flow', 'surface_flow', 'pathlines', 'residence_times']
        scales = [(None,None)] * 6 + [(0,10), (0,10)]

        visu.visual2D(object_list=obj_list, color_scale=scales, lines=1000)

    # 3. Visualisation 3D
    if run_3d:
        print(f"Opening 3D Visualizer for {model_name}...")
        visu.visual3D(interactive=True,
                      object_list=['grid', 'watertable', 'watertable_depth',
                                   'surface_flow', 'drain_flow', 'pathlines'],
                      view='south-west', z_scale=10)


def plot_rmodel_pathlines(model_path, geographic, stable_folder, vmin=0.1, vmax=100):
    """Cartographie des lignes de flux colorées par temps de résidence."""
    # Chemins
    path_shp = os.path.join(model_path, '_postprocess', '_particles', 'pathlines_weighted.shp')
    end_shp = os.path.join(model_path, '_postprocess', '_particles', 'starting_weighted.shp')
    bound_shp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    dem_path = geographic.watershed_box_buff_dem

    # Chargement
    shp_pathlines = gpd.read_file(path_shp)
    shp_endpoints = gpd.read_file(end_shp)
    watershed_boundary = gpd.read_file(bound_shp)

    with rasterio.open(dem_path) as dem_rio:
        dem_data = dem_rio.read(1)
        dem_data = np.ma.masked_where(dem_data < 0, dem_data)
        extent = rasterio.plot.plotting_extent(dem_rio)

    # Setup Couleurs (Log scale)
    norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
    cmap = 'jet'

    fig, ax = plt.subplots(1, 1, figsize=(8, 8))

    # 1. DEM en fond (Gris)
    ax.imshow(dem_data, cmap='Greys', alpha=0.5, extent=extent, zorder=1)

    # 2. Limite bassin
    watershed_boundary.plot(ax=ax, facecolor='None', edgecolor='black', lw=2, zorder=2)

    # 3. Pathlines
    shp_pathlines.plot(ax=ax, column='time_win_y', cmap=cmap, norm=norm, lw=1, zorder=3)

    # 4. Points de départ (Seepage)
    shp_endpoints.plot(ax=ax, column='time_win_y', cmap=cmap, norm=norm,
                       markersize=15, edgecolor='k', lw=0.5, zorder=4)

    ax.set_title(f'Residence times - {os.path.basename(model_path)}')

    # Colorbar
    im = cm.ScalarMappable(cmap=cmap, norm=norm)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    plt.colorbar(im, cax=cax, label='Time [years]')

    return fig, ax


def plot_streamflow_comparison(geographic,df_obs, model_path, model_name,
                               xlim=['2002', '2005'], ylim=[-5, 100]):
    """Compare le débit observé (Qobs) avec les résultats simulés du dossier model_path."""

    sim_path = os.path.join(model_path, '_postprocess/_timeseries/_simulated_timeseries.csv')
    if not os.path.exists(sim_path):
        return None
    area = int(round(geographic.catch_area))

    Qobs_path = data_path / 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
    Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
    date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
    Qobs.index = date
    Qobs = Qobs[2].to_frame(name="Q")
    Qobs = Qobs / 1000 # L/d to m3/d
    Qobs = (Qobs / (area*1000000)) # m3/d to m/day
    Qobs = Qobs.resample('ME').mean()
    # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    # Qobs = select_period(Qobs, 2003, 2003)
    Qobs = Qobs * 30 * 1000
    # Chargement simulation
    Smod = pd.read_csv(sim_path, sep=';', index_col=0, parse_dates=True)

    # Calculs (m/day -> mm/month)
    Rmod = Smod['recharge'] * 30 * 1000
    rmod = Smod['runoff'] * 30 * 1000
    Omod = Smod['outflow_drain'] * 30 * 1000
    Qmod = Omod + rmod

    # Plot
    fig, ax = plt.subplots(1, 1, figsize=(12, 4), dpi=300)

    ax.plot(df_obs, color='k', lw=2, label='Observed')
    ax.plot(Qmod, color='red', lw=2, label='Simulated (Outflow+Runoff)')
    ax.plot(Rmod, color='dodgerblue', lw=2, ls='--', label='Recharge')

    ax.set_xlim(pd.to_datetime(xlim[0]), pd.to_datetime(xlim[1]))
    ax.set_ylim(ylim)
    ax.set_ylabel('Q / A [mm/month]')
    ax.legend()
    ax.set_title(model_name.upper())

    # Formatage dates
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    plt.tight_layout()
    return fig, ax