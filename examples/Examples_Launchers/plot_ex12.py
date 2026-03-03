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
import plotly.graph_objects as go
import base64
from io import BytesIO
from PIL import Image
import os, glob
import flopy.utils.binaryfile as bf
import imageio
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import matplotlib.cm as cm
from mpl_toolkits.axes_grid1 import make_axes_locatable
import rasterio
import geopandas as gpd
import os, glob
from PIL import Image
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

def plot_cross_section(stable_folder, simulations_folder, model_name, geographic):
        fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)
        print(stable_folder)

        mask = imageio.v2.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        watertable_elevation = np.load(os.path.join(simulations_folder, model_name, '_postprocess', 'watertable_elevation.npy'), allow_pickle=True).item()

        dem_data = imageio.v2.imread(geographic.watershed_dem)
        wt_data = watertable_elevation[2]

        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)

        cur_x = dem_data.shape[1] /2
        cur_x = 50

        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        dem_v_plot = dem_prof[:,int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        wt_v_plot = wt_prof[:,int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan

        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1.5)
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
        d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-20, color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-20, color='dimgray', lw=1.5)

        ax.set_xlim(1500, 4900)
        ax.set_ylim(90, 130)
        ax.set_yticks([90,100,110,120,130])
        ax.set_xlabel('Distance [m]')
        ax.set_ylabel('Elevation [m]')

        plt.tight_layout()
        plt.show()

# ============================================================================
# PLOT STREAMFLOW - WITH DYNAMIC FACTOR PARAMETER
# ============================================================================

def plot_streamflow(geographic, data_path, simulations_folder, vers, factor=30, time_index=None):
    """Plot streamflow - with dynamic factor for different examples

    Parameters:
    -----------
    factor : int, default=30
        Scaling factor for data (30 for monthly ex12, 7 for weekly ex09)
    time_index : DatetimeIndex, optional
        Real datetime index to remap Smod when CSV stores integers
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
            print(f" Warning: Could not load observed streamflow: {e}")
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
                    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True, date_format='mixed')
                    # Remap integer index to real dates if available
                    if time_index is not None and len(time_index) == len(Smod):
                        Smod.index = time_index
                    elif 'date' in Smod.columns:
                        Smod.index = pd.to_datetime(Smod['date'])
                        Smod = Smod.drop(columns=['date'])
                    break
                except Exception:
                    continue

        if Smod is None:
            print(f"Warning: Could not find timeseries file for {model_name}, skipping...")
            plt.close(fig)
            continue

        Rmod = Smod['recharge'] * factor * 1000
        rmod = Smod.get('runoff', Smod['recharge'] * 0) * factor * 1000

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
        plt.show()


# ============================================================================
# PLOT PIEZOMETRY - WITH DYNAMIC FACTOR PARAMETER
# ============================================================================

def plot_piezometry(geographic, simulations_folder, vers, factor=30, time_index=None):
    """Plot piezometry - with dynamic factor for different examples

    Parameters:
    -----------
    factor : int, default=30
        Scaling factor for data (30 for monthly ex12, 7 for weekly ex09)
    time_index : DatetimeIndex, optional
        Real datetime index to remap Smod when CSV stores integers
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
                    Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True, date_format='mixed')
                    # Remap integer index to real dates if available
                    if time_index is not None and len(time_index) == len(Smod):
                        Smod.index = time_index
                    elif 'date' in Smod.columns:
                        Smod.index = pd.to_datetime(Smod['date'])
                        Smod = Smod.drop(columns=['date'])
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
        axb.set_yticks([0, 100])
        axb.set_yticklabels([0, 100])
        axb.legend(loc='upper right')
        plt.show()


# ============================================================================
# PLOT PATHLINES - EXACT FROM example12.py lines 613-683
# ============================================================================

def plot_pathlines( simulations_folder, model_name, stable_folder, geographic):

    shp_pathlines = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'pathlines_weighted.shp'))
    shp_endpoints = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'starting_weighted.shp'))
    line = gpd.read_file(os.path.join(stable_folder, 'geographic', 'watershed.shp'))

    dem_rio = rasterio.open(geographic.watershed_box_buff_dem)
    dem_data = dem_rio.read(1)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)

    norm = mcolors.LogNorm(vmin=0.1, vmax=100)
    im = cm.ScalarMappable(cmap='jet', norm=norm)
    im.set_array([])

    fig, ax = plt.subplots(1,1, figsize=(8,6))
    rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform, cmap='Greys', alpha=0.7, zorder=-10)
    shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=1, norm=norm, zorder=1)
    shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5, markersize=20, legend=False, norm=norm, zorder=2, edgecolor='k')
    line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)
    ax.set_title('Residence times - backward from seepage [y]', fontsize=10)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    fig.colorbar(im, cax=cax, orientation='vertical')
    fig.tight_layout()
    plt.show()

# ============================================================================
# PLOT CONCENTRATION - EXACT FROM example12.py lines 851-1050
# ============================================================================

def plot_concentration( vers, model_mt3dms, model_modflow, simulations_folder, stable_folder, R_mm_day_filt, geographic, hydrography, initializing):


    vgif_name = vers
    gif_name = vgif_name+'.gif'
    plot_gif = True
    input_no3 = model_mt3dms.sconc_input[1].mean() * 1000

    ucnobj  = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt+'.UCN')
    concobj_1c = ucnobj.get_alldata(mflay=None)
    concobj_1c_fil = concobj_1c.copy() * 1000
    concobj_1c_fil[concobj_1c_fil>=1e30] = np.nan
    concobj_1c_fil_surf = {}
    the_mins, the_maxs = [], []

    for i in range((model_mt3dms.model_modflow.nper)):
        the_time = i
        seep = imageio.v2.imread(os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif'))
        concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time+1][0]
        concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])
        the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
        the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

    all_box_stats = []
    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    if not os.path.exists(figures_dir): os.makedirs(figures_dir)
    mean_vals, mean_times = [], []

    # Generate hillshade first if not already present (like example12.py line 1157)
    hill_path = os.path.join(stable_folder, 'geographic', 'watershed_hill.tif')
    if not os.path.exists(hill_path):
        wbt.hillshade(
            os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'),
            hill_path
        )
    dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
    hill = rasterio.open(hill_path)

    for i in range(len(concobj_1c_fil_surf)):
        the_time = i
        conc_plt = concobj_1c_fil_surf[i]
        xi = conc_plt.flatten()
        xi = xi[~np.isnan(xi)]
        xpos = mdates.date2num(R_mm_day_filt.index[i])
        if xi.size == 0: continue

        q10, q90, median, mean = np.nanmin(xi), np.nanmax(xi), np.nanmedian(xi), np.nanmean(xi)
        box_stats = [{'med': median, 'mean': mean, 'q1': q10, 'q3': q90, 'whislo': q10, 'whishi': q90, 'fliers': []}]
        mean_vals.append(mean)
        mean_times.append(xpos)
        all_box_stats.append((xpos, box_stats))

        fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})
        ax = axs.ravel()
        axb = ax[0].twinx()
        ax[0].zorder, axb.zorder = 1, 0
        ax[0].patch.set_visible(False)

        for xpos_b, box_stat in all_box_stats:
            ax[0].bxp(box_stat, positions=[xpos_b], widths=5, showfliers=False, showmeans=True, meanline=False,
                    boxprops=dict(color='forestgreen'), medianprops=dict(color='forestgreen'),
                    meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5))

        ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)
        ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1, label='Injection: 50 mg/L')
        ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
        ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax[0].set_ylim(30, 100); ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))
        ax[0].plot(mean_times, mean_vals, color='black', lw=2)
        axb.step(R_mm_day_filt.index, R_mm_day_filt * 30, lw=2, color='dodgerblue')

        norm = mcolors.LogNorm(vmin=30, vmax=100)
        sm = cm.ScalarMappable(cmap='turbo', norm=norm); sm.set_array([])
        rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)), ax=ax[1], transform=hill.transform, cmap='Greys_r', alpha=0.75, zorder=-10)
        rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, conc_plt.copy()), ax=ax[1], transform=dem.transform, cmap='turbo', alpha=1, zorder=1)

        gpd.read_file(geographic.watershed_shp).plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
        gpd.read_file(hydrography.streams).plot(ax=ax[1], color='navy', lw=1, zorder=0)

        divider = make_axes_locatable(ax[1])
        cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
        fig.add_axes(cax)
        fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
        fig.savefig(figures_dir+vgif_name+'_'+str(i)+'_'+model_modflow.model_name+'.png', dpi=300, bbox_inches='tight')
        plt.close(fig)
        plt.show()
    if plot_gif:
        filenames = sorted(glob.glob(figures_dir + vgif_name + '*.png'), key=os.path.getmtime)
        images = [Image.open(img) for img in filenames]
        images[0].save(figures_dir + '_' + gif_name, save_all=True, append_images=images[1:], duration=200, loop=0)

    # PLOT INTERACTIVE
    dem_data_int = imageio.v2.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif'))
    stream_data_int = imageio.v2.imread(os.path.join(stable_folder,'hydrography','botopage2024_naizin_streams_perennial-intermittent.tif'))
    watertable_data_int = imageio.v2.imread(os.path.join(simulations_folder,model_modflow.model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif'))
    from hydromodpy.viz import visualization_results
    visu = visualization_results.Visualization(initializing, geographic, hydrography, model_modflow.model_name)
    visu.interactive_cross_section(dem_data_int, watertable_data_int, stream_data_int, True)
# ============================================================================
# PLOT 2D - EXACT FROM example12.py lines 708-735
# ============================================================================

def plot_2d(initializing, geographic, hydrography, model_name):
    """Plot 2D visualization - EXACT from example12.py"""
    try:
        if hydrography is None:
            print(" Warning: Hydrography data not available, skipping 2D visualization")
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
        print(f" Error in 2D visualization: {e}")


# ============================================================================
# PLOT 3D - EXACT FROM example12.py lines 737-758
# ============================================================================

def plot_3d(initializing, geographic, hydrography, model_name):
    """Plot 3D visualization - EXACT from example12.py"""
    try:
        if hydrography is None:
            print(" Warning: Hydrography data not available, skipping 3D visualization")
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

def plot_interactive_section(stable_folder, simulations_folder, model_name, initializing, geographic, hydrography):
    import imageio
    import os
    from hydromodpy.viz import visualization_results

    # CLICK on the map to select a cross-section !
    dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
    stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','botopage2024_naizin_streams_perennial-intermittent.tif')) # river data
    watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
    interactive = True
    visu = visualization_results.Visualization(initializing, geographic, hydrography, model_name)
    visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)
# ============================================================================
# WEB ANIMATION - EXACT FROM example12.py lines 1069-1156
# ============================================================================

def plot_web_animation(simulations_folder, vers):


    # Exemple : création de la liste des fichiers
    figures_dir = os.path.join(str(simulations_folder), '_figures/')
    begin_by = figures_dir + vers
    filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)

    # Charger toutes les images en base64
    def image_to_base64(path):
        with Image.open(path) as img:
            with BytesIO() as stream:
                img.save(stream, format="png")
                return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

    image_sources = [image_to_base64(p) for p in filenames]

    if not image_sources:
        print(f"No PNG files matching {begin_by}*.png were found")
        return

    base_image = dict(
        source=image_sources[0],
        xref="paper", yref="paper", x=0.5, y=0.5,
        sizex=1, sizey=1, xanchor="center", yanchor="middle",
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
                type="buttons", showactive=False, y=1.05, x=1.15, xanchor="right", yanchor="top",
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
                "x": 0.5, "xanchor": "center", "y": -0.01, "yanchor": "top", "len": 0.85, "pad": {"t": 40}
            }]
        ),
        frames=frames
    )

    fig.update_layout(width=1600, height=900, margin=dict(l=60, r=60, t=60, b=90))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.show("browser")


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
    plt.show()
    if save_path:
        plt.savefig(save_path, dpi=300)
    return fig, axs

