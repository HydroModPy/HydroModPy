# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt

import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
# import seaborn as sns
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
import earthpy.spatial as es
import earthpy.plot as ep

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                 
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- 

#%% PATH WATERSHED

user = 'Clement'
user = 'Ronan'

if user == 'Clement':
    #############################################################
    git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_data/")
    # Path where the results will be stored
    out_path = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_permanent/_out/")
    # Figure folder outputs
    figsim_folder = os.path.join("D:/GoogleDrive/1.TRAVAIL/PYTHON/FLOPY/_figures/")
    #############################################################

if user == 'Ronan':
    #############################################################
    git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
    # Path to the data folder
    data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/"
    # Path where the results will be stored
    out_path = "D:/Users/abherve/DYNAMIC/"
    # Figure folder outputs
    figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures2/_outputs/'
    #############################################################

dems_path = data_path + 'DEM/' # reginal DEM or conceptual DEM
#shp_path = data_path + 'SHAPEFILE/' # if you want run a model from a shapefile
modflow_path = git_path + 'examples/_example/modflow/' # add bin/ folder with necessary .exe

surfex_path =  os.path.join(data_path,"SURFEX") # add surfex models in .h5 format (France scale, else, specify None)
drias_path = data_path + 'DRIAS/Lasset/from_ronan/'
geology_path = data_path + 'GEOLOGY/France/Layer/' # add geologic layers
oceanic_path = data_path + 'OCEANIC/' # add specific sea level files
hydrology_path = data_path + 'HYDROLOGY/' # add hydrographic shapefiles
hydrometry_path = data_path + 'HYDROMETRY/' # add hydrometry data for automatic download
intermittency_path = data_path + 'HYDROLOGY/France/Intermittency/' # add intermittency data for automatic download
piezometry_path = False # add piezometry data for automatic download
subbasin_path = False # generate subbasins from stations or manual points

dem_name = "BDALTI_25M_09_MERGED.tif" # name of dem
from_shp = None # specify a path if process start from a given shapefile
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None

from_xy = []
# Depending on the choices
dem_path = dems_path + dem_name

library_path = git_path + 'watershed/' + 'watershed_library.csv' # each row is a study site with outlet coordinates
# watershed_names = ['Pompage'] # search the name in watershed_library or just label your result folder

watershed_names = ['Lasset']
code_names = ['?']

#%% GENERATE WATERSHED

load = True

for watershed_name in watershed_names[:]:

    print('##### '+watershed_name.upper()+' #####')

    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=[],
                                  cell_size=cell_size)
    
    # watershed_display.watershed_dem(BV)
    # watershed_display.watershed_local(dem_path, BV)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
#%% ADD AND CLIP SPECIFIC DATA

# # Climat
# BV.add_surfex(surfex_path)
# BV.add_drias(drias_path)

# # Landscape
# BV.add_geology(geology_path)
# BV.add_oceanic(oceanic_path)

# Hydrology
#% Merger les points shp
# pt_streams = hydrology_path + 'stream_digit_pt.shp'
# pt_zh = hydrology_path + 'zh_digit_pt.shp'
# merge_path = pt_streams+';'+pt_zh
# pt_zhstreams = hydrology_path + 'zhstreams_pt.shp'
# wbt.merge_vectors(merge_path, pt_zhstreams)

# #Merger les tifs
# tif_streams = hydrology_path + 'stream_digit.tif'
# tif_zh = hydrology_path + 'zh_digit.tif'
# merge_path = tif_streams+';'+tif_zh
# tif_zhstreams = hydrology_path + 'zhstreams.tif'
# wbt.mosaic(tif_zhstreams, inputs=merge_path, method="nn")

types_obs = ["zhstreams_dissolved"] # shapefile cours d'eau

#types_obs = ['streams'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid'] # list of shapefile name columns to translate as a tif
BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

# # Measurements
# BV.add_hydrometry(hydrometry_path)
# BV.add_intermittency(intermittency_path)
# # BV.add_piezometry()

# # Zones
# BV.add_subbasin()

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% ----

#%% PLOT RECHARGE DRIAS

gcm_list = ['CNR','MPI','HAD','ECE','IPS','NOR']
rcm_list = ['ALA','CCL','REG','RCA','WRF','R15','RAC','R09','HIR']
mix_list = ['MPI-CCL','ECE-RCA','ECE-RAC','IPS-RCA','CNR-RAC','NOR-R15',
            'CNR-ALA','NOR-HIR','HAD-CCL','IPS-WRF','HAD-REG','MPI-R09'] #GCM - RCM format

# for gcm in gcm_list:
# for rcm in rcm_list:
    
for mix in mix_list:
    gcm = mix.split('-')[0]
    rcm = mix.split('-')[1]
    BV.forcing.update_recharge_drias(gcm, rcm, 'historic', 1990, 1990, sim_state='transient')
    BV.forcing.update_runoff_drias(gcm, rcm, 'historic', 1990, 1990, sim_state='transient')
    recharge = BV.forcing.recharge
    runoff = BV.forcing.runoff
    plt.plot(recharge)
    plt.yscale('log')

#%% PLOT OBSERVED DISCHARGE

figsim_folder = 'folder path for output figures'

watershed_names = ['Lasset']

first = 1990
last = 2023
one = 2001

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    ### AJOUTER LA CHRONIQUE DE DEBIT OBSERVE DANS LE DOSSIER HYDROMETRY 
    Qobs_path = glob.glob(stable_folder+'hydrometry/'+'Hydrometric_'+'*')[0] # path du csv
    
    Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename('Q')
    area = BV.geographic.area
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) * 1000 # m3/s to mm/j
    Qobs = select_period(Qobs, first, last)
    data_index = Qobs.copy()

    mean_mensual = data_index.resample('M').mean() # mensual mean
    mean_annual = data_index.resample('Y').mean() # annual mean
    Mean = round(data_index.mean(),2)
    Mean = data_index.mean()
    Min = data_index.resample('Y').min()
    Q10 = data_index.resample('Y').quantile(0.10)
    Q25 = data_index.resample('Y').quantile(0.25)
    Q50 = data_index.resample('Y').quantile(0.50)
    Q75 = data_index.resample('Y').quantile(0.75)
    Q90 = data_index.resample('Y').quantile(0.90)
    Max = data_index.resample('Y').max()
    mean_interan_days = data_index.groupby([data_index.index.month,
                                    data_index.index.day], as_index=True).mean().to_frame()
    std_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).std()
    q10_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.10)
    q90_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.90)
    q50_interan_days = data_index.groupby([data_index.index.month,
                        data_index.index.day], as_index=True).quantile(0.50)
    mean_interan_days['std'] = std_interan_days
    mean_interan_days['q10'] = q10_interan_days
    mean_interan_days['q90'] = q90_interan_days
    mean_interan_days['q50'] = q50_interan_days
    mean_interan_days.index.names = ['months','days']
    mean_interan_days = mean_interan_days.reset_index()
    # mean_interan_days.months = mean_interan_days.months.replace(
    #                                     [10,11,12,1,2,3,4,5,6,7,8,9],
    #                                     [1,2,3,4,5,6,7,8,9,10,11,12])
    mean_interan_days = mean_interan_days.sort_values(['months','days'])
    mean_interan_days['counts'] = np.array(range(1,len(mean_interan_days)+1))
    # mean_interan_days.q10 = mean_interan_days.q10.replace(0,0.01)
    fig, ax = plt.subplots(figsize=(5,4))
    # ax.plot(mean_interan_days.counts, mean_interan_days[station+'_mmm'],
    #         lw=1, color='red', label='Mean')
    ax.plot(mean_interan_days.counts, mean_interan_days.q50,
            lw=2, color='darkred', label='Median')
    yerrmax = mean_interan_days.q90
    yerrmin = mean_interan_days.q10
    ax.fill_between(mean_interan_days.counts, yerrmin, yerrmax,
                      color='cyan',edgecolor='grey',
                      alpha = 0.5, label='10-90th')
    plt.yscale('log')
    # ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(0,366)
    ax.set_ylim(0.01,100)
    ax.tick_params(axis='both', which='major', pad=10)
    x1 = np.linspace(0,366,13)
    squad = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
    ax.set_xticks(x1)
    ax.set_xticklabels(squad, minor=False, rotation='horizontal')
    ax.set_xlabel('Months', labelpad=+10)
    ax.set_ylabel('Q / A [mm/day]',labelpad=+10)
    ax.set_title(watershed_name + ' [' + str(first) + ' to ' + str(last) + ']')
    ax.grid(color='grey', lw=0.5, zorder=0)
    dates = np.array([one],dtype=np.int64)
    colors = ['blue']
    for z in np.array(range(len(dates))):
        onlyone = data_index[(data_index.index.year==dates[z])].to_frame()
        onlyone = onlyone.groupby([onlyone.index.month,
                                    onlyone.index.day], as_index=True).mean()
        onlyone['counts'] = np.array(range(1,len(onlyone)+1))
        ax.plot(onlyone.counts, onlyone['Q'],
                color=colors[z], lw=1, label = str(dates[z]))
    ax.legend(loc='upper left')
    plt.tight_layout()
    # fig.savefig(path + 'plot_figures/' + site + '/' + 'regime' + '.png', dpi=300, bbox_inches='tight')
    # fig.savefig(path_fig+'/'+watershed_name+'_intermensual_'+name_file+'.png', dpi=300, bbox_inches='tight')
    # fig.savefig(figsim_folder+'/'+watershed_name+'_intermensual'+'.png', dpi=300, bbox_inches='tight')

#%% PLOT OBSERVED HYDROGRAPHIC

################ A REFAIRE AVEC DATA

types_obs = ['streams'] # list of shapefile name layers for clip hydrology
fields_obs = ['fid']

df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)

for watershed_name in watershed_names[:] :
       
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    bv = gpd.read_file(BV.geographic.watershed_shp)
    area = BV.geographic.area
    area = round(area, 1)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    path_hydro = stable_folder + 'hydrology/'
    complete = gpd.read_file(path_hydro+'complete.shp')
    intermittent = gpd.read_file(path_hydro+'intermittent.shp')
    perennial = gpd.read_file(path_hydro+'perennial.shp')
    river = gpd.read_file(path_hydro+'river.shp')
    
    if watershed_name == 'Canut':
        zh = gpd.read_file(path_hydro+'zh_meuchezecanut.shp')
        zh_tif = imageio.imread(path_hydro+'zh_meuchezecanut.tif')
    if watershed_name == 'Nancon':
        zh = gpd.read_file(path_hydro+'zh_couesnon.shp')
        zh_tif = imageio.imread(path_hydro+'zh_couesnon.tif')
        
    perennial_tif = imageio.imread(path_hydro+'perennial.tif')
    intermittent_tif = imageio.imread(path_hydro+'intermittent.tif')
    river_tif = imageio.imread(path_hydro+'river.tif')
    complete_tif = imageio.imread(path_hydro+'complete.tif')
    
    area_complete = round((np.sum(complete_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_zh = round((np.sum(zh_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_intermittent = round((np.sum(intermittent_tif > 0) * 75**2) / 1000000 / area*100, 1)
    area_perennial = round((np.sum(perennial_tif > 0) * 75**2) / 1000000 / area*100, 1)
    area_river = round((np.sum(river_tif > 0) * 75**2) / 1000000 / area *100, 1)
    area_all = round(area_complete + area_zh, 1)
    drainage = round(area_all / area, 2)
    
    fig, ax = plt.subplots(1,1, figsize=(5,5))

    polyg = gpd.read_file(BV.geographic.watershed_shp)
    contour = gpd.read_file(BV.geographic.watershed_contour_shp)
    dem = rasterio.open(BV.geographic.watershed_box_buff_dem)

    bounds = dem.bounds
    xlim = ([bounds[0], bounds[2]])
    ylim = ([bounds[1], bounds[3]])
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'bottom', location='upper left')
    ax.add_artist(scalebar)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.set_title(watershed_name, fontproperties=fontprop)
    ax.set(aspect='equal')
    
    cmap = 'gist_earth' # 'Greys'
    cmap = 'Greys'
    wbt.hillshade(BV.geographic.watershed_box_buff_dem,
                  stable_folder+'geographic/'+'watershed_box_buff_dem_hill.tif',
                  azimuth=315.0, 
                  altitude=30.0, 
                  zfactor=10)
    hill = rasterio.open(stable_folder+'geographic/'+'watershed_box_buff_dem_hill.tif')
    show(hill.read(1), ax=ax, transform=dem.transform, cmap='Greys_r', alpha=0.5, zorder=2, aspect="auto")
    image_hidden = ax.imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                             cmap=cmap, alpha=0.75)
    show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=ax, transform=dem.transform, 
          cmap=cmap, alpha=0.55, zorder=2, aspect="auto")
    
    zh.plot(ax=ax, lw=0, color='navy', alpha=1, zorder=4, legend=True, label='Wetlands')

    streams = complete.copy()
    streams[streams.persistanc=='Permanent'].plot(ax=ax, lw=2, color='dodgerblue',
                                                  zorder=6,legend=True, label='Streams')
    streams[streams.persistanc=='Intermittent'].plot(ax=ax, lw=2, color='darkorange', ls='-',
                                                  zorder=5,legend=True, label='Streams')
    contour.plot(ax=ax, lw=1.5, color='k', zorder=4,legend=True, label='Watershed')
    try:
        if os.path.exists(BV.piezometry.piezos_shp):
            piezos = gpd.read_file(BV.piezometry.piezos_shp)
            piezos.plot(ax=ax, color='blue', marker='^', zorder=6, 
                        edgecolor='k', lw=1, legend=True, label='Piezometers: continue')
    except:
        pass
    try:
        if len(BV.piezometry.x_coord_discrete)>0:
            ax.scatter(BV.piezometry.x_coord_discrete, BV.piezometry.y_coord_discrete,
                       c='forestgreen',
                       marker='^', zorder=5, label='Piezometers: discrete')
    except:
        pass   
    try:
        if os.path.exists(BV.hydrometry.hydrometric_clip):
            hydromet = gpd.read_file(BV.hydrometry.hydrometric_clip)
            hydromet.plot(ax=ax, color='yellow', zorder=7, marker='o', markersize=70,
                          edgecolor='k', lw=1, legend=True, label='Hydrometric: continue')
    except:
        pass 
    try:
        if os.path.exists(BV.intermittency.onde_clip):
            intermit = gpd.read_file(BV.intermittency.onde_clip)
            intermit.plot(ax=ax, color='yellow', zorder=8, marker='s',markersize=50,
                          edgecolor='black', lw=1, legend=True, label='Intermittency: discrete')
    except:
        pass
    
    divider = make_axes_locatable(ax)
    cax = divider.append_axes(size="2%",position='right', pad=0.05)
    fig.add_axes(cax)
    cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
    cbar.ax.get_ymajorticklabels()
    list(cbar.get_ticks())
    val = np.ma.masked_where(BV.geographic.dem_box_data < 0, BV.geographic.dem_box_data)
    minVal =  int(round(np.min(val[np.nonzero(val)],0)))
    maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
    meanVal = int(round(minVal+((maxVal-minVal)/2),0))
    cbar.set_ticks([minVal, meanVal, maxVal])
    cbar.set_ticklabels([minVal, meanVal, maxVal])
    cbar.mappable.set_clim(minVal, maxVal)
    cbar.ax.tick_params(labelsize=10)
    cbar.ax.yaxis.set_ticks_position('right')
    cbar.ax.tick_params(size=2)
    #cbar.set_label('Elevation (m)', size=12)
    
    ax.text(0.015, 0.14, 
            'BV = ' +str(area) + ' [km²]' + '\n'
            'All = '+str(area_all) + ' [%]' + '\n'
            'Wetlands = '+str(area_zh) + ' [%]' + '\n'
            'Network = '+str(area_complete) + ' [%]' + '\n'
            'Standard = '+str(area_river) + ' [%]' + '\n'
            'Intermit. = '+str(area_intermittent) + ' [%]' + '\n'
            'Perenn. = '+str(area_perennial) + ' [%]',
            horizontalalignment='left',
            verticalalignment='center', 
            transform=ax.transAxes,
            fontsize = 6, zorder=10)
    
    path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed.shp'
    sub = gpd.read_file(path_sub)
    sub.plot(ax=ax, facecolor='none', edgecolor='k', lw=1, zorder=6)
    
    fig.tight_layout()
    
    # fig.savefig(out_path+'/_figures/'+watershed_name+'_hydromapping2'+'.png', dpi=300, bbox_inches='tight')

#%% ----

#%% INIT CALIB DICHOTOMY STREAMS

from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis

watershed_names = ['Lasset']

for watershed_name in watershed_names[:] :
    
    types_obs = ['zhstreams'] # list of shapefile name layers for clip hydrology
    fields_obs = ['fid']
        
    df = pd.DataFrame(np.nan, index=range(1), columns=types_obs)
    
    for type_obs, field_obs in zip(types_obs, fields_obs):
   
        print('##### '+watershed_name.upper()+' #####')
        
        BV = watershed_root.Watershed(watershed_name=watershed_name,
                                      dem_path=dem_path, 
                                      out_path=out_path,
                                      load=True,
                                      modflow_path=modflow_path)
        area = BV.geographic.area
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
            
        # BV.add_hydrology(hydrology_path, types_obs=[type_obs], fields_obs=[field_obs])
        
        BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
                                          first_year = 1960, last_year=2019, time_step = 'D',
                                          sim_state='steady') #
        
        # BV.hydrodynamic.update_porosity(0.1)
        # BV.hydrodynamic.update_hyd_cond(2)
        BV.hydrodynamic.update_nlay(1)
        BV.hydrodynamic.update_thickness(30)
        BV.hydrodynamic.update_bottom(None)
        BV.hydrodynamic.update_cond_decay(0)
        BV.hydrodynamic.update_thick_exp(1)
        
        params_df = pd.DataFrame(columns=['params',
                                          'init_values','lower_bounds','higher_bounds',
                                          'units','scale'])
        params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+00,'m/j','lin']
        
        params_file = 'calib_dicot_hom_1v_k1'
        
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

        # params_file = 'calib_dicot_het_2v_k1-k2'
        # params_file = 'calib_dicot_hom_2v_k1-n1'
        
#%% RUN CALIB DICHOTOMY STREAMS

calib = calib_root.Calibration(params_file, BV, observations = ['streams'])
dicot = calib.dichotomy(gap=1)

#%% PLOT CALIB DICHOTOMY STREAMS

for i, type_obs in enumerate(types_obs):
    
    typ_calib = 'streams_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                       key=os.path.getmtime)
    name_file = list_path[i].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    test.display_objective_function(save=None)
    
    koptim = test.calib['params_values'][-1]
    kr = koptim / test.calib['recharge']
    obj_func = test.calib['objective_function'][-1]
    
    # df.loc[0,watershed_name] = koptim / 24 / 3600
    # df.loc[1,watershed_name] = kr
    # df.loc[2,watershed_name] = obj_func
    
    df.loc[0,type_obs] = koptim / 24 / 3600
    df.loc[1,type_obs] = kr
    df.loc[2,type_obs] = obj_func
    
df.to_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')
df = pd.read_csv(BV.calibration_folder+'/'+watershed_name+'_koptims_dichotomy_streams.csv', sep=';')

#%% INIT CALIB EXPLORATION DISCHARGE

# CHANGER LA CHRONIQUE ALL_D de surfex, colonne REA

watershed_names = ['Lasset']

# modflow_path = data_path + 'SOFTWARE/MODFLOW/'

from watershed import watershed_root, watershed_display, forcing
from calibration import calib_root, calib_dichotomy, calib_analysis, calib_exploration, calib_basis, calib_params

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    
    sim_state = 'transient'
    
    #### STAY IN D TO GENERATE RECHARGE ####
    # If necessary, you resample in month before to update the last recharge (integrated in the model)
    time_step = 'D'
    
    var = 'REC'
    wr = True
    wish = 0
    mod = 'REA'
    
    raw_path = stable_folder+'/'+'hydrometry/'
    
    ### AJOUTER LA CHRONIQUE DE DEBIT OBSERVE DANS LE DOSSIER HYDROMETRY 
    Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
    Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
    area = BV.geographic.area
    Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
    Qobs = Qobs.squeeze()
    # Qobs = Qobs.resample('D').mean()
    fqobs = Qobs.first_valid_index().year+1
    lqobs = Qobs.last_valid_index().year-1
    
    # Ces dates permettent de normalizer et calibrer sur des périodes différentes, à voir ci-dessous
    # fhist = 2021
    # lhist = 2021
    
    # fcalib = 2021
    # lcalib = 2021
    
    # year_min = 2021
    # year_max = 2021
    
    ############ METHOD 1 : BUILT RECHARGE ALONE ############
    '''
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                              first_year = 1960, last_year = 2019,
                                              time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = 1960, last_year=2019,
                                          time_step = time_step, sim_state=sim_state)
    Runof = BV.forcing.runoff # m/month
    
    dates = pd.date_range(start='1/1/2021', end='31/12/2022', freq='D', closed=None)
    
    Rech_averag = Rech.groupby([Rech.index.month,
                                Rech.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
    Rech_averag = Rech_averag.append(Rech_averag, ignore_index=True)
    Rech_averag.index = dates
    Runof_averag = Runof.groupby([Runof.index.month, 
                                  Runof.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
    Runof_averag = Runof_averag.append(Runof_averag, ignore_index=True)
    Runof_averag.index = dates
    
    norm_Rech = select_period(Rech_averag, 2021, 2022)
    norm_Qobs = select_period(Qobs, 2021, 2022)
    
    Rt_Rech_Qobs = (norm_Qobs.mean() / norm_Rech.mean())
    print(Rt_Rech_Qobs.round(2))
    Nt = (norm_Rech * Rt_Rech_Qobs)
    
    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    plt.plot(BV.forcing.recharge, c='r')
    plt.plot(Qobs, c='b')
    plt.yscale('log')
    '''
    
    ############ METHOD 2 : TAKE RECHARGE SURFEX AFTER MODIFY _ALL_D FILE ############
    
    # Method 1 is applied for the runoff
    
    BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                              first_year = 1960, last_year = 2019,
                                              time_step = time_step, sim_state=sim_state)
    Rech = BV.forcing.recharge
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                          first_year = 1960, last_year=2019,
                                          time_step = time_step, sim_state=sim_state)
    Runof = BV.forcing.runoff # m/month
    
    norm_Rech = select_period(Rech_averag, 2021, 2022)
    norm_Qobs = select_period(Qobs, 2021, 2022)
    
    Rt_Rech_Qobs = (norm_Qobs.mean() / norm_Rech.mean())
    print(Rt_Rech_Qobs.round(2))
    Nt = (norm_Rech * Rt_Rech_Qobs)
    BV.forcing.update_recharge(Nt, sim_state=sim_state)
    plt.plot(BV.forcing.recharge, c='r')
    plt.plot(Qobs, c='b')
    plt.yscale('log')
    
    BV.forcing.update_recharge(select_period(BV.forcing.recharge, 2021, 2022), sim_state=sim_state)
    
    # Need to add 2021 and 2022 runoff SURFEX, in _ALL_D.csv or with the method behind
    dates = pd.date_range(start='1/1/2021', end='31/12/2022', freq='D', closed=None)
    Runof_averag = Runof.groupby([Runof.index.month, 
                                  Runof.index.day], as_index=True).mean().reset_index().iloc[:,-1:].iloc[:-1]
    Runof_averag = Runof_averag.append(Runof_averag, ignore_index=True)
    Runof_averag.index = dates
    
    BV.forcing.update_runoff(select_period(Runof_averag, 2021, 2022), sim_state=sim_state)

    ##### TO CHANGE IN MENSUALLY MODEL BECAUSE THE CALIBRATION ON Q IS NOW MENSUALLY #####
    Rech_mens = BV.forcing.recharge.resample('M').mean().squeeze() # to transform in pandas series
    Runof_mens = BV.forcing.runoff.resample('M').mean().squeeze() # to transform in pandas series
    
    BV.forcing.update_recharge(Rech_mens, sim_state=sim_state)
    BV.forcing.update_runoff(Runof_mens, sim_state=sim_state)
    
    plt.plot(BV.forcing.recharge, c='darkorange')
    plt.plot(Qobs.resample('M').mean(), c='forestgreen')
    plt.yscale('log')

    BV.hydrodynamic.update_nlay(1)
    BV.hydrodynamic.update_bottom(None)
    BV.hydrodynamic.update_cond_decay(0)
    BV.hydrodynamic.update_thick_exp(1)
    BV.hydrodynamic.update_thickness(30)
    # BV.hydrodynamic.update_porosity(0.001)
    # BV.hydrodynamic.update_hyd_cond(0.08640) # 1e-6 m/s
    
    params_df = pd.DataFrame(columns=['params',
                                      'init_values','lower_bounds','higher_bounds',
                                      'units','scale'])
    
    params_df.loc[0] = ['k1',8.64e-01,8.64e-03,8.64e+00,'m/j','lin']
    params_df.loc[1] = ['n1',0.01,0.001,0.10,'m/j','lin']

    params_file = 'calib_explo_hom_2v_k1-n1'
    
    list_npy = glob.glob(BV.calibration_folder+'/'+params_file+'/hydrometry_calibration/_watershed/'+'*'+'.npy')
    for npy in list_npy:
        os.remove(npy)
    
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)

# x= pd.read_csv('C:/Users/ronan/Downloads/_ALL_D.csv',
#                sep=';', parse_dates=True, index_col=0)
# plt.plot(select_period(x,2015,2025)['REC_REA_historic'])

#%% RUN CALIB EXPLORATION DISCHARGE

calib = calib_root.Calibration(params_file, BV, observations = ['hydrometry'])
calib.exploration(resolution=100)

#%% PLOT CALIB EXPLORATION DISCHARGE

watershed_names = ['Lasset']

params_file = 'calib_explo_hom_2v_k1-n1'

wish = 0 # va chercher la dernière calibration (simulation)

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)

    ##########
    typ_calib = 'hydrometry_calibration'
    list_path = sorted(glob.glob(os.path.join(BV.calibration_folder, params_file, typ_calib, '*.calib')),
                        key=os.path.getmtime, reverse=True)
    name_file = list_path[wish].split('\\')[-1]
    calib_file = os.path.join(BV.calibration_folder, params_file, typ_calib, name_file)
    test = calib_analysis.CalibAnalysis(calib_file)
    # test.display_objective_function(save=None)
    # test.find_best_values()
    # test.display_best_data()
    
    sim_res=test.sim_results
    # x= pd.to_numeric(test.sim_results[test.params_synt[0]]['seepage_areas'])
    # plt.plot(x)
    
    # path_fig = os.path.join(BV.calibration_folder, params_file, typ_calib, '_figures')
    path_fig = os.path.join(out_path, '_figures')
    
    # CHRONICS
    
    typ_name = typ_calib.split('_')[0]
    
    obs = test.data_obs
    sim = test.data_sim
    ind = test.data_ind
    obj = test.calib['objective_function']
    xyz = test.params_xyz
    
    synt = test.params_synt
        
    p1 = []
    for p in synt:
        p1.append(p.split(';')[0])
    p2 = []
    for p in synt:
        p2.append(p.split(';')[1])
    rout = []
    for r in sim[typ_name]:
        rout.append((r*1000*30).mean()[0])
    rsat = []
    for t in range(len(synt)):     
        # sat = test.sim_results[synt[t]]['seepage_areas']
        # sat = test.sim_results[synt[t]]['surflow_areas']
        sat = pd.to_numeric(sat, errors='coerce').isnull()
        rsat.append(sat.mean())
    
    nse_good = []
    sat_good = []
    
    fig, axs = plt.subplots(2,2, figsize=(9,5))
    axs = axs.ravel()
    fig.suptitle(watershed_name.upper())
    
    numb = 0
    for i in range(len(obs[typ_name])):
        o = obs[typ_name][i] * 1000 * 30 # m/j to mm/month
        s = sim[typ_name][i] * 1000 * 30 # m/j to mm/month
        nd = ind[typ_name][i]
        # sat = test.sim_results[synt[i]]['seepage_areas']
        sat = test.sim_results[synt[i]]['surflow_areas']
        sat = pd.to_numeric(sat, errors='coerce')
        
        k = '{:.1e}'.format(float(synt[i].split(';')[0])/24/3600)
        sy = float(synt[i].split(';')[1]) * 100
        title = 'Discharge [mm/month]'
        nselog = round(((nd[0]))*100,1)
        label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
                '$NSE_{log}$ = '+str(nselog)+'%'
        nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
                
        if nselog > 0:
            if all(i <= 100 for i in sat):
                numb += 1
                
        # c = []
        # for h in range(len(ind[typ_name])):
        #     d = ind[typ_name][h][0]
        #     c.append(d)
        c = np.linspace(0,1,len(obs[typ_name]))
        # c = np.linspace(0,1,numb)

        cmap = mpl.cm.get_cmap('viridis_r')

        color_gradients = cmap(c)
        # vmin = min(c)
        # vmax = max(c)
        # norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
        
        def fmt_xaxes(ax):
            yearsmaj = mdates.YearLocator(5)   # every year
            yearsmin = mdates.YearLocator(1)
            # monthsmaj = mdates.MonthLocator(6)  # every month
            # monthsmin = mdates.MonthLocator(3)
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            years_fmt = mdates.DateFormatter('%Y')
            ax.xaxis.set_major_locator(yearsmaj)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
        
        if nselog >= 0:
            if all(i <= 100 for i in sat):       
                
                ax = axs[0]
                fmt_xaxes(axs[0])
                # ax.xaxis.set_major_locator(yearsmaj)
                # ax.xaxis.set_minor_locator(yearsmin)
                # ax.xaxis.set_major_formatter(years_fmt)
                
                ax.plot(s, color=color_gradients[i], lw=1, label=label)
                # ax.plot(s, lw=1, label=label)   
                ax.set_title(title)
                ax.plot(o, color='grey', lw=3, ls='-', zorder=0)
                # ax.set_xlim(pd.to_datetime('1989'), pd.to_datetime('2021'))

                del(ax)
                
                ax = axs[1]
                fmt_xaxes(axs[1])
                ax.set_title('Log discharge [mm/month]')
                ax.plot(o.copy(), color='grey', lw=3, ls='-', zorder=0)
                ax.set_yscale('log')
                ax.plot(s.copy(), color=color_gradients[i], lw=1, label=label)
                # ax.xaxis.set_major_locator(yearsmaj)
                # ax.xaxis.set_minor_locator(yearsmin)
                # ax.xaxis.set_major_formatter(years_fmt)

                ax = axs[2]
                fmt_xaxes(axs[2])   
                sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
                ax.plot(sat.copy(), color=color_gradients[i], lw=1, label=label)
                # ax.plot(sat, lw=1, label=label) 
                ax.set_ylim(-2,50)
                title = 'Saturation [%]'
                ax.set_title(title)
                # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
                            
    plt.tight_layout()
    
    if watershed_name == 'Nancon':
        ncol = 2
    else:
        ncol = 1
    ax.legend(bbox_to_anchor=(1.2,0.5), prop={'size': 5}, loc="center left", borderaxespad=0, 
              ncol=ncol)
    ax = axs[3]
    plt.axis('off')

    # plt.tight_layout()

    # fig.savefig(path_fig+'/'+watershed_name+'_chronics_'+name_file+'.png', dpi=300, bbox_inches='tight')

    # ax.plot(BV.forcing.recharge, color='grey', lw= 5)
           
    # divider = make_axes_locatable(ax)
    # cax = divider.append_axes('right', size='1.25%', pad=0.1)
    # fig.add_axes(cax)
    # norm = Normalize(vmin=vmin, vmax=vmax)
    # n_cmap = cm.ScalarMappable(norm=norm, cmap=cmap)
    # n_cmap.set_array([])
    # ax.get_figure().colorbar(n_cmap, cax=cax, orientation="vertical")
    
    # SAT

    fig, axs = plt.subplots(1,3, figsize=(10,3.5))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    for k in range(3):
        ax = axs[k]
        ax.axes.tick_params(which='both', direction='out', zorder=10)
        X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
        Z = np.empty((3,3,))
        Z[:] = np.nan
        p1 = test.params_values[0]
        p2= test.params_values[1]
        sim_sat = np.zeros((len(p1),len(p2)))
        compt=0
        for i in range(len(p1)):
            for j in range(len(p2)):
                temp = [p1[i],p2[j]]
                string = str(p1[i])+';'+str(+p2[j])
                if k == 0:
                    try:
                        ax.set_title('SAT MIN [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).min()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).min()
                    except:
                        pass
                if k == 1:
                    try:
                        ax.set_title('SAT MEAN [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).mean()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).mean()
                    except:
                        pass
                if k == 2:
                    try:
                        ax.set_title('SAT MAX [%]')
                        # sim_sat[j][i] = pd.to_numeric(sim_res[string]['seepage_areas']).max()
                        sim_sat[j][i] = pd.to_numeric(sim_res[string]['surflow_areas']).max()
                    except:
                        pass
                compt += 1
        Z=sim_sat
        pc = ax.contourf(X,Y,Z,cmap='jet', levels=np.arange(0,51,5)) #figadd.cmap_white_jet()
        ax.set_xscale('log')
        # cb = fig.colorbar(pc)
        ax.set_ylabel('Sy [-]')
        ax.set_xlabel('K [m/j]')
        # cb.set_label('Saturation [%]', rotation=270, labelpad=40)
   
    position=fig.add_axes([1.05,0.2,0.02,0.7])  ## the parameters are the specified position you set 
    fig.colorbar(pc,cax=position)
    plt.tight_layout()
    # fig.savefig(path_fig+'/'+watershed_name+'_saturation_'+name_file+'.png', dpi=300, bbox_inches='tight')

    # DISCHARGE
    
    fig, axs = plt.subplots(1,3, figsize=(15,4))
    fig.suptitle(watershed_name.upper())
    axs = axs.ravel()
    
    ax = axs[0]
    
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    # Z[Z<0] = 0
    from numpy import inf
    # Z[Z == inf] = 0
    pc = ax.imshow(Z, vmin = 0, vmax=1, aspect='auto') #figadd.cmap_white_jet() , shading='gouraud'
    # ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb=fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # fig.savefig(path_fig+'/'+'_shaded_'+name_file+'.png', dpi=300, bbox_inches='tight')

    ax = axs[1]
    
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    # Z[Z == inf] = np.nan
    # Z = np.ma.array(Z,mask=np.isnan(Z))
    # Z = np.ma.masked_invalid(Z)
    # Z = Z.replace(np.inf, np.nan)
    pc = ax.pcolormesh(X,Y,Z, cmap='jet', shading='gouraud', vmin=0, vmax=1) #figadd.cmap_white_jet()
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    # cb.set_ticklabels(np.arange(0,1.1,0.1))
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    # fig.savefig(path_fig+'/'+'_mesh_'+name_file+'.png', dpi=300, bbox_inches='tight')

    ax = axs[2]
    ax.axes.tick_params(which='both', direction='out', zorder=10)
    X,Y = np.meshgrid(test.params_values[0], test.params_values[1])
    Z=test.obj_function.copy()
    Z[Z<0] = 0
    from numpy import inf
    Z[Z == inf] = 0
    # np.ma.masked_where(test.obj_function<0, test.obj_function)
    # plt.pcolor(X,Y,Z,cmap='jet')#figadd.cmap_white_jet()
    bounds = np.arange(0,1.1,0.1)
    norm = mpl.colors.Normalize(vmin=-1, vmax=1.0)
    # norm = mpl.colors.BoundaryNorm(boundaries=bounds, ncolors=256)
    # pc = ax.contourf(X, Y, Z, vmin=0, vmax=1, norm = norm)
    pc = ax.contourf(X, Y, Z, levels=np.arange(0,1.1,0.1))    
    # plt.imshow(Z)
    # plt.xlim(1)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.05)
    # cb = fig.colorbar(pc)
    cb = fig.colorbar(pc, cax=cax, orientation='vertical')
    cb.set_ticks(np.arange(0,1.1,0.1)) 
    # cb.set_ticklabels(np.arange(0,1.1,0.1))
    cb.set_label('$NSE_{log}$', rotation=270, labelpad=40)
    ax.set_xscale('log')
    ax.set_ylabel('Sy [-]')
    ax.set_xlabel('K [m/j]')
    
    plt.tight_layout()
    
    # fig.savefig(path_fig+'/'+watershed_name+'_discharge_'+name_file+'.png', dpi=300, bbox_inches='tight')

#%% ----

#%% PARAM RUN MODEL

watershed_names = ['Lasset']
types_obs = ['streams'] # list of shapefile name layers for clip hydrology

typ = 'projec' # sinu / hist / proj

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    # BV.add_hydrometry(hydrometry_path)
    # BV.add_intermittency(intermittency_path) 
    # BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)
    # BV.add_subbasin()
    
    # Input recharge
    bzh_rech = False
    var = 'REC'
    wr = True
    
    ##### MODEL CHOICE ==> LOOP ####
    
    # for mod in ['NOR1']:
    #     for sce in ['RCP2.6','RCP8.5']:
        
    for gcm, rcm in zip(['CNR'],['ALA']):
        for sce in ['RCP2.6','RCP8.5']:
            mod = gcm
            
    # for mod in ['REA']:
    #     for sce in ['historic']:
            
            # Choice temporal of the simulation
            sim_state = 'transient' # 'steady' or 'transient'
            init_rech = None # 'first'
            
            if mod == 'REA':
                period_hist = [1990,2019]
            else:
                period_hist = [1990,2010] # recharge period
            period = [2098,2099] # recharge period               
            
            first_hist = period_hist[0]
            last_hist = period_hist[1]
            first = period[0]
            last = period[1]
            time_step = 'M' # or 'D'
            actual_date = True # False if date is conceptual
            start = str(period[0])+'-01-01' # necessary to specify the first time_step date
            
            raw_path = stable_folder+'/'+'hydrometry/'
            Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
            Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
            area = BV.geographic.area
            # area = float(Qobs_path.split('_')[-3])
            # print(area)
            Qobs = (Qobs / (area*1000000)) * (3600 * 24) # m3/s to m/day
            Qobs = Qobs.squeeze()
            Qobs = Qobs.resample('M').mean()
            
            # # Normalize discharge historic
            # BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
            #                                   first_year = first_hist, last_year = last_hist,
            #                                   time_step = time_step, sim_state = sim_state)
            # Rech_hist = BV.forcing.recharge
            # BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
            #                                 first_year = first_hist, last_year = last_hist,
            #                                 time_step = time_step, sim_state = sim_state)
            # Runof_hist = BV.forcing.runoff # m/month
            
            # Rech_hist_select = select_period(Rech_hist, first_hist, last_hist)
            # Q_hist_select = select_period(Qobs, first_hist, last_hist)
            # Ratio_hist = (Q_hist_select.mean() / Rech_hist_select.mean())
            # print(Ratio_hist.round(2))
            
            # Rech_hist_norm = (Rech_hist_select * Ratio_hist)    

            # if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            #     BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
            #                                       first_year = first, last_year = last,
            #                                       time_step = time_step, sim_state = sim_state)
            #     Rech_fut = BV.forcing.recharge
            #     BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce=sce,
            #                                     first_year = first, last_year = last,
            #                                     time_step = time_step, sim_state = sim_state)
            #     Runof_fut = BV.forcing.runoff # m/month
                                
            #     Rech_fut_norm = (Rech_fut * Ratio_hist)
            
            #     Rech_concat = pd.concat((Rech_fut_norm, Rech_hist_norm), axis=1).mean(axis=1)
            #     Runof_concat = pd.concat((Runof_fut, Runof_hist), axis=1).mean(axis=1)
            
            #     BV.forcing.update_recharge(Rech_concat, sim_state = sim_state)
            #     BV.forcing.update_runoff(Runof_concat, sim_state = sim_state)
                
            #     fig = plt.subplots(1,1)
            #     plt.plot(Rech_concat)
            #     plt.yscale('log')
                
            # else:
            #     BV.forcing.update_recharge(Rech_hist_norm, sim_state = sim_state)
            #     BV.forcing.update_runoff(Runof_hist, sim_state = sim_state)
            
            #     # fig = plt.subplots(1,1)
            #     plt.plot(Rech_hist_norm)
            #     plt.yscale('log')
            
            if mod == 'REA':
                BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                                  first_year = first_hist, last_year = last_hist,
                                                  time_step = time_step, sim_state = sim_state)
                Rech_hist = BV.forcing.recharge
                BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce=sce,
                                                first_year = first_hist, last_year = last_hist,
                                                time_step = time_step, sim_state = sim_state)
                Runof_hist = BV.forcing.runoff # m/month
            
            if mod != 'REA':
                BV.forcing.update_recharge_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = sce,
                                                  first_year = first, last_year = last,
                                                  sim_state = sim_state)
                Rech = BV.forcing.recharge.resample('M').mean()
                BV.forcing.update_recharge(Rech, sim_state=sim_state)
                BV.forcing.update_runoff_drias(gcm_mod=gcm, rcm_mod=rcm, sce_mod = sce,
                                                first_year = first, last_year = last,
                                                sim_state = sim_state)
                Runof = BV.forcing.runoff.resample('M').mean() # m/month
                BV.forcing.update_recharge(Runof, sim_state=sim_state)
                
            # Active of not modules
            box = False # if True generate a rectangular model
            sink_fill = False # permit to fill sinks
            modpath_sim = False # run modpath particle tracking if True
            verbose = True # add print of MODFLOW in console
            post_process = False # necessary to decompose post process of process
            
            # Strcture of the model
            lay_number = 1 # vertical discrtization
            bottom = None # aquifer flat or not
            thick_exp = 1 # exponential decay of K with nlay
            cond_decay = 0 # exponential decay of K with depth
            thick = 30 # m
            
            # Hydraulic properties
            Koptim = 2e-6 # koptim 1.4e-5 / 5.33e-5
            Sy = 0.01
                
            Ks = np.array([Koptim]) * 3600 * 24 # m/second to m/day
            Sys = [Sy]
            
        # RUN MODEL
        
            list_model_name = []
            list_of_success = []
            list_flow_model = []
            
            compt = 1
            # Update properties
            for Sy in Sys:
                for K in Ks:
                    # K = 1e-5
                    # Sy = 0.01
                    # print(K)
                    BV.hydrodynamic.update_thickness(thick)
                    BV.hydrodynamic.update_hyd_cond(K) 
                    BV.hydrodynamic.update_porosity(Sy)
                      
                    date_today = datetime.now().strftime("%d/%m/%Y %H:%M:%S") # just a string
                    date_today = date_today.replace('/','-')
                    date_today = date_today.replace(':','-')
                    date_today = date_today.replace(' ','_')
                    
                    model_name = typ+'_'+str(compt)+'_'+\
                                 var+'-'+mod+'-'+sce+'_'+\
                                 str(Sy*100)+'-'+str(round(K,2))+'-'+str(thick)+'_'+\
                                 str(first)+'-'+str(last)

                    # Run model
                    try:
                        print('SIM - ' + model_name)
                        success, flow_model = BV.run_modflow(ident=model_name,
                                                             modpath_sim=modpath_sim,
                                                             sink_fill=sink_fill,
                                                             box=box,
                                                             lay_number=lay_number,
                                                             bottom=bottom,
                                                             thick_exp=thick_exp,
                                                             cond_decay=cond_decay,
                                                             verbose=verbose,
                                                             post_process=post_process, 
                                                             init_rech=init_rech)
                        if success == True:
                            print(     'Success')
                        else:
                            print(     'Error')
                    except:
                        pass
                    list_model_name.append(model_name)
                    list_of_success.append(success)
                    list_flow_model.append(flow_model)
                    compt+=1
                    
            print(list_of_success)
            
            dictio = {}
            dictio['list_model_name'] = list_model_name
            dictio['list_of_success'] = list_of_success
            dictio['list_flow_model'] = list_flow_model
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            # dictio.to_hdf(h5file)
            dd.io.save(h5file, dictio)
            
            # import pickle
            # with open(h5file, 'wb') as handle:
            #     pickle.dump(dictio, handle, protocol=pickle.HIGHEST_PROTOCOL)
        
            # BV.list_flow_model = list_flow_model
            # BV.list_of_success = list_success
            # BV.save_object()
    
#%% POSTPROCESS MODEL

typ = 'projec'
# typ = 'identname'

watershed_names = ['Lasset']
types_obs = ['streams'] # list of shapefile name layers for clip hydrology

for watershed_name in watershed_names[:] :
    
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)
    
    for mod in ['CNR']:
        for sce in ['RCP2.6','RCP8.5']:
    
    # for mod in ['REA']:
    #     for sce in ['historic']:
    
            h5file = simulations_folder+'/'+'list_'+typ+'_'+var+'-'+mod+'-'+sce
            d = dd.io.load(h5file)
            list_model_name = d['list_model_name'][:]
            list_of_success = d['list_of_success'][:]
            list_flow_model = d['list_flow_model'][:]
            
            for model_name, success, flow_model in zip(list_model_name, list_of_success, list_flow_model):
                    
                if success==True:
                        print(success)
                        
                        BV.matrix_modflow(success,
                                          flow_model,
                                          first_only = False,
                                          watertable_elevation = True,
                                          watertable_depth = True, 
                                          seepage_areas = True,
                                          outflow_drain = True,
                                          groundwater_flux = True,
                                          specific_discharge = False,
                                          accumulation_flux = True,
                                          perenn_intermit_shp = False,
                                          groundwater_storage = True,
                                          verbose = True,
                                          export_tif = True)
                        
                        # Necessary for results_modflow
                        BV.forcing.update_recharge(flow_model.climatic,
                                                   sim_state=sim_state)
                        
                        # # Extract results
                        BV.results_modflow(ident=model_name,
                                           actual_date=actual_date,
                                           start=start,
                                           time_step=time_step)
                        
                        ## Plot maps
                        save_gif = False # save a gif after plots
                        Rech = flow_model.climatic
                        surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
                                                              types_obs, save_gif=save_gif, first_only=True,
                                                              outflow=True, accflux=True, intermittency=False,
                                                              chronics=True, sim_state=sim_state)

#%% ----

#%% PLOT CHRONICS MODEL

typ = 'identname'
mod = 'REA'
first = 1990
last = 2019
time_step = 'M'
sim_state = 'transient'

watershed_names = ['Lasset']

types_obs = ['streams'] # list of shapefile name layers for clip hydrology

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    scan = 'outflow_drain'
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    # simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
     
    BV.forcing.update_runoff_surfex(clim_mod = mod, clim_sce='historic',
                                    first_year = first, last_year = last, time_step = 'M',
                                    sim_state='transient')
    Runof = BV.forcing.runoff # m/month
    
    for simul in simul_list:
        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        Qmod = Smod['outflow_drain'] 
        Qmod = Qmod.squeeze() * 1000 * 30
        Qmod = Qmod + (BV.forcing.runoff * 1000 * 30)
        Cmod = Smod['recharge'] * 1000 * 30 # mm/months
        
        stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
        raw_path = stable_folder+'/'+'hydrometry/'
        Qobs_path = fnmatch.filter(os.listdir(raw_path), 'Hydrometric_*')[0]
        Qobs = pd.read_csv(raw_path+Qobs_path, sep=';', index_col=0, parse_dates=True)
        # area = float(Qobs_path.split('_')[-3])
        area = BV.geographic.area
        Qobs = (Qobs / (area*1000000)) * (3600 * 24 * 30) * 1000  # m3/s to mm/month
        Qobs = Qobs.squeeze()
        Qobs = select_period(Qobs, 1990, 2019)
        Qobs = Qobs.resample('M').mean()
        
        import hydroeval as he
        nse = he.evaluator(he.nse, Qmod, Qobs, transform='log')[0]
        print(round(nse,2))
        
        # plt.plot(Cmod)
        # plt.plot(Qobs)
        # plt.plot(Qmod)
        
        fig, axs = plt.subplots(2,1, figsize=(7,6))
        # axs = axs.ravel()
        
        yearsmaj = mdates.YearLocator(5)   # every year
        yearsmin = mdates.YearLocator(1)
        # monthsmaj = mdates.MonthLocator(6)  # every month
        # monthsmin = mdates.MonthLocator(3)
        # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
        years_fmt = mdates.DateFormatter('%Y')
        
        o = Qobs # m/j to mm/month
        s = Qmod # m/j to mm/month
        # nd = 
        sat = Smod['surflow_areas']
        
        k = '{:.1e}'.format(K)
        sy = Sy
        title = watershed_name
        # nselog = round(((nd[0]))*100,1)
        # label = 'K = '+k+' m/s'+' ; '+'ɸ = '+str(round(sy,1))+'% ; '+\
        #         '$NSE_{log}$ = '+str(nselog)+'%'
        # nse_good.append(str(k)+'_'+str(sy)+'_'+str(nselog))
        
        '''
        ax = axs[0]
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.plot(s, color='red', lw=2, label='modeled')
        # ax.plot(s, lw=1, label=label)   
        ax.set_title(title)
        ax.plot(o, color='grey', lw=2, ls='-', zorder=0, label='observed')
        ax.grid('grey')
        ax.set_ylim(-2,200)
        # ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
        ax.legend(loc='upper left')
        '''
        
        ax = axs[0]
        ax.set_ylabel('Q / A [mm/month]')
        axb = ax.twinx()
        axb.set_ylabel('R [mm/month]', rotation=270, labelpad=25)
        axb.bar(Cmod.index, Cmod,
                color='blue', edgecolor='blue', lw=2.5)
        axb.set_ylim(0,999)
        axb.invert_yaxis()
        # axb.xaxis.set_major_formatter_locator(yearsmaj)
        # axb.xaxis.set_minor_locator(yearsmin)
        # axb.xaxis.set_major_formatter(years_fmt)
        # ax.plot(R, color='k', lw=2, label='recharge')
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)
        ax.plot(o, color='k', lw=2, ls='-', zorder=0, label='observed')
        ax.set_yscale('log')
        ax.plot(s, color='red', lw=2, label='modeled')
        ax.set_ylim(0.11,999)
        # ax.grid('grey')
        # ax.set_title('Discharge')
        # ax.set_xlim(pd.to_datetime('1986'))
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        
        # fig, axs = plt.subplots(1,2, figsize=(7,4))
        ax = axs[1]
        ax.set_ylabel('$A_{sat}$ [%]')
        # axb = ax.twinx()
        # axb.set_ylim(0,1000)
        # axb.invert_yaxis()
        # ax.axhline(y=20, color='k', ls= '--', lw=2)
        ax.xaxis.set_major_locator(yearsmaj)
        ax.xaxis.set_minor_locator(yearsmin)
        ax.xaxis.set_major_formatter(years_fmt)    
        # sat_good.append(str(k)+'_'+str(sy)+'_'+str(round(sat.mean(),2)))
        ax.plot(Smod['surflow_areas'], color='darkorange', ls='-', lw=2, label='catchment')
        ax.fill_between(Smod.index, Smod['perenn_areas'], Smod['surflow_areas'],
                        interpolate=False, color='darkorange', alpha=0.75)
        # ax.plot(Smod['intermit_areas'], color='darkorange', lw=2, label='upstream')
        ax.plot(Smod['perenn_areas'], color='dodgerblue',
                marker=None, markeredgecolor='none', markerfacecolor='dodgerblue',
                markersize=5, lw=2, label='upstream')
        ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                        interpolate=False, color='dodgerblue', alpha=0.75)
        # ax.plot(sat, lw=1, label=label) 
        ax.set_ylim(0,20)
        # title = 'Saturation'
        # ax.set_title(title)
        ax.set_xlim(pd.to_datetime('1990'), pd.to_datetime('2020'))
        # ax.grid('grey')
        # ax.set_xlim(pd.to_datetime(str(first)), pd.to_datetime(str(last)))
        
        '''
        fig, ax = plt.subplots(1,1, figsize=(6,3))
        Sub_path = glob.glob(simul+'/_subbasins/intermittency_*')[0]+'/_simulated_results.csv'
        Sub = pd.read_csv(Sub_path, sep=';', index_col=0, parse_dates=True)
        # ax.axhline(y=20, color='grey', ls='--', lw = 1, label='approxim. observed')
        # ax.plot(Sub['perenn_areas'], color='dodgerblue', lw=2)
        # ax.plot(Sub['intermit_areas'], color='darkorange', lw=2)
        # ax.legend(loc='upper left')
        d = BV.intermittency.flowing
        assec = d[d==1].dropna()
        invi = d[d==2].dropna()
        low = d[d==3].dropna()
        accep = d[d==4].dropna()
        visib = d[d==5].dropna()
        
        # for u in range(len(noflow)):
        #     ax.axvline(noflow.index[u], color='salmon', linewidth = 5, alpha=1)
        # for u in range(len(flow)):
        #     ax.axvline(flow.index[u], color='lightskyblue', linewidth = 5, alpha=1)
            
        for u in range(len(assec)):
            ax.axvline(assec.index[u], color='salmon', linewidth = 5, alpha=1) # assec
        for u in range(len(invi)):
            ax.axvline(invi.index[u], color='gold', linewidth = 5, alpha=1) # pond
        for u in range(len(low)):
            ax.axvline(low.index[u], color='lightskyblue', linewidth = 5, alpha=1) # bio mal
        for u in range(len(accep)):
            ax.axvline(accep.index[u], color='lightskyblue', linewidth = 5, alpha=1) # bio ok
        for u in range(len(visib)):
            ax.axvline(visib.index[u], color='lightskyblue', linewidth = 5, alpha=1) # ecoul
        
        ax.axhline(y=0, color='dimgray', lw= 1)

        ax.set_xlim(pd.to_datetime('2012'), pd.to_datetime('2020'))
        seep = Sub['seepage_areas']
        seep = seep.fillna(0)
        ax.plot(seep, color='k', ls=(0, (1, 1)), lw=1.5, label='upstream')
        tp = Sub['surflow_areas']
        tp = tp.fillna(0)
        ax.plot(tp, color='k', lw=1.5, label='upstream')
        # cond_coul = 0
        # flow_mod = tp.copy()
        # flow_mod[flow_mod<=cond_coul] = np.nan
        # ax.plot(flow_mod, color='navy', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        # noflow_mod = tp.copy()
        # noflow_mod[noflow_mod>cond_coul] = np.nan
        # ax.plot(noflow_mod, color='darkred', marker='o', markersize=3,
        #         markeredgecolor='none',
        #         lw=2, label='upstream')
        ax.grid('grey', axis='x')
        ax.set_ylim(-0.6,20)
        ax.set_ylabel('$A_{sat}$ [%]')
        
        months_maj = MonthLocator(7)  # every x month
        ax.xaxis.set_minor_locator(months_maj)
        '''
        
        plt.tight_layout()
        
        # ax.legend(bbox_to_anchor=(1.5, 3), ncol=1)
        # fig.savefig(path_fig+'/'+'_chronic_'+name_file+'.png', dpi=300, bbox_inches='tight')
        # fig.savefig(simul+'/_figures/png/'+'quickly_plot_results'+'.png', dpi=300, bbox_inches='tight')

#%% PLOT INTERMITTENTCY MAP

typ = 'identname'

typ_intermit = 'yearly' # yearly or persistency or monthly
gif = True

watershed_names = ['Lasset']

types_obs = ['streams'] # list of shapefile name layers for clip hydrology

for watershed_name in watershed_names[:] :
    print('##### '+watershed_name.upper()+' #####')
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True,
                                  modflow_path=modflow_path)

    years = np.arange(first,last+1,1)
    
    simul_list = glob.glob(simulations_folder+typ+'*')
    simul_list = sorted(glob.glob(simulations_folder+typ+'*'),
                       key=os.path.getmtime)
    # simuls = fnmatch.filter(os.listdir(simulations_folder), typ+'*')
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line <= 0, line)
    
    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
        
    for simul in simul_list:
    
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        for key in acc_npy:
            # print(key)
            mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
            # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
            acc_npy[key] = np.ma.masked_array(acc_npy[key], mask=(mask<0))
        zero = acc_npy[0] * 0
        for l in range(len(acc_npy)):
            tempo = acc_npy[l].copy()
            tempo[tempo>0] = 1
            zero = zero + tempo
        days_flux = zero.copy() # / len(acc_npy)
        
        if typ_intermit == 'persistency':
            fig, ax = plt.subplots(1,1, figsize=(7,6))
            
            days_flux = days_flux / len(acc_npy)
            im = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                            cmap = 'coolwarm_r', vmin=0, vmax=1, alpha=1)
            ax.imshow(np.ma.masked_where(days_flux < 1, days_flux),
                      cmap = mpl.colors.ListedColormap('navy'), alpha=1)
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            
            divider = make_axes_locatable(ax)
            cax = divider.append_axes('right', size='5%', pad=0.05)
    
            fig.colorbar(im, cax=cax, orientation='vertical',)
    
            ax.set_title(str(years[0])+' to '+str(years[-1]))
            fig.savefig(simul+'/_figures/png/'+'map_intermittent_persistency'+'.png', dpi=300, bbox_inches='tight')
            
        acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
        inf = 0
        sup = 12
        compt = 0
        step = int(round(len(acc_npy)/12))
        
        for i in range(step):
            print(str(i)+'/'+str(step))
            interv = list(acc_npy.items())[inf:sup]
            # print(interv)
            for key in range(len(interv)):
                # key = tupl[0]
                # print(key)
                interv[key] = np.ma.masked_array(interv[key][1], mask=(mask<0))
                
            zero = acc_npy[0] * 0
            for j in range(len(interv)):
                tempo = interv[j].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy()
            days_flux = np.ma.masked_array(days_flux, mask=(mask<0))
            days_flux = np.ma.masked_array(days_flux, mask=(days_flux<=0))
            
            if typ_intermit == 'monthly':
                if i > 20:
                    for k in range(len(interv)):
                        to = interv[k].copy()
                        
                        # fig, ax = plt.subplots(1,1, figsize=(7,6))
                        # ax.imshow(to)
                        
                        to[(to>0) & (days_flux==12)] = 2
                        to[(to>0) & (days_flux<12)] = 1
                        
                        to = np.ma.masked_array(to, mask=(mask<0))
                        to = np.ma.masked_array(to, mask=(to<=0))
                        
                        fig, ax = plt.subplots(1,1, figsize=(7,6))
                        # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                        ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                        ax.imshow(np.ma.masked_where(to==1, to), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                        ax.imshow(np.ma.masked_where(to==2, to), cmap = mpl.colors.ListedColormap(['darkorange']))
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        ax.get_xaxis().set_visible(False)
                        ax.get_yaxis().set_visible(False)
                        
                        ax.set_title(str(years[i])+'-'+(str(k+1)))
                        
                        path_sub = glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.shp'
                        wbt.vector_lines_to_raster(path_sub,
                                                   glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif',
                                                   base = stable_folder+'geographic/'+'watershed_dem.tif')
                        line_sub = imageio.imread(glob.glob(stable_folder+'subbasin/' + '/intermittency*')[0] + '/watershed_contour.tif')
                        line_sub = np.ma.masked_where(line_sub <= 0, line_sub)
                        ax.imshow(line_sub, cmap=mpl.colors.ListedColormap('dimgray'))
                        
                        ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                        
                        fig.savefig(simul+'/_figures/png/'+'map_intermittent_monthly_'+str(compt)+'.png', dpi=300, bbox_inches='tight')
        
                        plt.close()
                        
                        compt += 1
                        
                    inf+=12
                    sup+=12
                    
                    if gif == True:
                        begin_by = simul+'/_figures/png/'+'map_intermittent_monthly'
                        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
                        images = []
                        for filename in filenames:
                            images.append(imageio.imread(filename))
                        imageio.mimsave(simul+'/_figures/gif/'+'map_intermittent_monthly'+'.gif', images, duration=0.5, loop=0)
                
            if typ_intermit == 'yearly':
                fig, ax = plt.subplots(1,1, figsize=(7,6))
                # image_hidden = ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys')
                ax.imshow(np.ma.masked_where(mask<0, mask), cmap='Greys', alpha=0.5, zorder=0)
                ax.imshow(np.ma.masked_where(days_flux<12, days_flux), cmap = mpl.colors.ListedColormap(['dodgerblue']))
                ax.imshow(np.ma.masked_where(days_flux==12, days_flux), cmap = mpl.colors.ListedColormap(['darkorange']))
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
    
                ax.set_title(years[i])
            
                # divider = make_axes_locatable(ax)
                # cax = divider.append_axes("right", size="1%", pad=0.05)
                # fig.add_axes(cax)
                # cbar = fig.colorbar(image_hidden, cax=cax, orientation="vertical")
                # val = np.ma.masked_where(mask < 0, mask)
                # minVal =  int(round(np.min(val[np.nonzero(val)],0)))
                # maxVal =  int(round(np.max(val[np.nonzero(val)],0)))
                # meanVal = int(round(minVal+((maxVal-minVal)/2),0))
                # cbar.set_ticks([minVal, meanVal, maxVal])
                # cbar.set_ticklabels([minVal, meanVal, maxVal])
                # cbar.mappable.set_clim(minVal, maxVal)
                # cbar.ax.tick_params(labelsize=10)
            
                fig.savefig(simul+'/_figures/png/'+'map_intermittent_yearly_'+str(i)+'.png', dpi=300, bbox_inches='tight')
                plt.close()
                
                inf+=12
                sup+=12
                
            if gif == True:
                begin_by = simul+'/_figures/png/'+'map_intermittent_yearly'
                filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
                images = []
                for filename in filenames:
                    images.append(imageio.imread(filename))
                imageio.mimsave(simul+'/_figures/gif/'+'map_intermittent_yearly'+'.gif', images, duration=0.5, loop=0)
        
#%% PLOT CROSS SECTION 2D

watershed_name = 'Lasset'

interactive = True
dem_data = BV.geographic.dem_data # dem data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(0).tif') # watertable data
river_data = imageio.imread(stable_folder+'/hydrology/'+'streams.tif') # river data

modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=interactive)

#%% PLOT STEADY STATE CATCHMENT

from tools import vtk
from groundwater_flow import visualization
#☻vtk.VTK(BV, 'modflow')
visu = visualization.Visualization(BV, model_name)
visu.visual2D(object_list = ['map', 'grid', 'watertable', 'watertable_depth','drain_flow',
                              'surface_flow'],
              color_scale = [(None,None),(None,None),(None,None),(0,10),
                              (None,None),(None,None)])
# visu.visual2D(object_list = ['pathlines', 'residence_times'],
#               color_scale = [(None,None),(None,None)], 
#               lines=100)

#%% PLOT BINS DISTRIBUTIONS

from scipy.stats import binned_statistic

x = Smod.recharge * 30 * 1000
y = Smod.outflow_drain * 30 * 1000

x = np.log(x)
y = np.log(y)

# Method 1
fig, ax = plt.subplots()
ax.scatter(x,y, s=9)
s, edges, _ = binned_statistic(x,y, statistic='mean', bins=np.logspace(min(x),max(x),100))
ys = np.repeat(s,2)
xs = np.repeat(edges,2)[1:-1]
ax.hlines(s,edges[:-1],edges[1:], color="crimson", )
for e in edges:
    ax.axvline(e, color="grey", linestyle="--")
ax.scatter(edges[:-1]+np.diff(edges)/2, s, c="limegreen", zorder=3)
ax.set_xscale("log")
ax.set_yscale("log")
plt.show()

# Method 2
import numpy as np
import matplotlib.pyplot as plt
nbins = 10
n, _ = np.histogram(x, bins=nbins)
sy, _ = np.histogram(x, bins=nbins, weights=y)
sy2, _ = np.histogram(x, bins=nbins, weights=y*y)
mean = sy / n
std = np.sqrt(sy2/n - mean*mean)
fig, ax = plt.subplots()
plt.plot(x, y, 'bo')
plt.errorbar((_[1:] + _[:-1])/2, mean, yerr=std, fmt='r-')
plt.show()

#%% ----

#%% FIG - Map of persistency index

typ = 'identname'

watershed_names = ['Lasset']

var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic']

fig2, axs2 = plt.subplots(1,1, figsize=(5,4),
                        sharex=True, sharey=True)

y_name = 'surflow_areas'

for watershed_name in watershed_names:

    color = 'k'

    fig1, axs1 = plt.subplots(1,1, figsize=(10,10), sharex=True, sharey=True)
    # axs1 = axs1.ravel()
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots

    for ix in np.arange(1,1+1,1):
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
        
        ax = axs1
            
        for sce in sce_list:
            # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
            
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+sce+'*')[0]
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            
            acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
            acc_npy = list(acc_npy.items())[-360:]
            # acc_npy = list(acc_npy.items())[360:720]
            
            for key in range(len(acc_npy)):
                # print(key)
                mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
            zero = acc_npy[0] * 0
            for i in range(len(acc_npy)):
                tempo = acc_npy[i].copy()
                tempo[tempo>0] = 1
                zero = zero + tempo
            days_flux = zero.copy() / len(acc_npy)
                    
            # ax = ax1
            vmin = 0
            vmax = 1
            
            cmap = plt.cm.jet_r  # define the colormap
            # cmap = parula_map
            cmaplist = [cmap(i) for i in range(cmap.N)]
            # cmaplist[0] = (.5, .5, .5, 1.0)
            cmap = mpl.colors.LinearSegmentedColormap.from_list(
                'Custom cmap', cmaplist, cmap.N)
            bounds = np.arange(0, 1.1, 0.1)
            norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                    
            pc = ax.imshow(np.ma.masked_where(days_flux <= 0, days_flux),
                           cmap=cmap, norm=norm, alpha=1)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            ax.axis('off')
            
            wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                                       stable_folder+'geographic/'+'watershed_contour.tif',
                                       base = stable_folder+'geographic/'+'watershed_dem.tif')
            line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
            line = np.ma.masked_where(line <= 0, line)
            import matplotlib as mpl
            ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
            # ax.set_title(params, fontsize=8)
            plt.subplots_adjust(hspace = -0.6)
            
            ax = axs2
            
            ### Classic histogram
            # masked = days_flux[days_flux >= 0]
            # Z = masked.flatten()
            # from scipy.stats import norm
            # pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none', alpha = 0.5)
            # ax.set_yscale('log')
        
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            ### Normalized cumulative evolution of areas in time
            X2 = np.sort(Smod[y_name])
            N = len(Smod[y_name])
            # ax.plot((1-np.arange(0,N,1)/N)*100, (X2-X2.min())/(X2.max()-X2.min()) * 100,
            #         color=color, lw=2)
            ax.plot((1-np.arange(0,N,1)/N)*100, (X2),
                    color=color, lw=2)
            ax.set_xlabel('percent_time [%]')
            ax.set_ylabel(y_name)
            # ax.set_xlim(-5,100)
            # ax.set_ylim(-5,100)
            # ax.set_xscale('log')
            # ax.set_yscale('log')
            
    position=fig1.add_axes([0.93,0.35,0.01,0.30])  ## the parameters are the specified position you set 
    fig1.colorbar(pc,cax=position, orientation="vertical")
    position.set_ylabel('Persistency index [-]', rotation=270, labelpad=40)
    
    # fig1.savefig(figsim_folder+watershed_name+'_persistency_map_historic'+'.png', dpi=300, bbox_inches='tight')

#%% FIG - Map of persistency index anomaly historic vs future

import matplotlib as mpl

watershed_names = ['Lasset']

typ = 'projec' # name of your identname for future simulations

var = 'REC'
scan = 'outflow_drain'

wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                           stable_folder+'geographic/'+'watershed_contour.tif',
                           base = stable_folder+'geographic/'+'watershed_dem.tif')
line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
line = np.ma.masked_where(line < 0, line)

for watershed_name in watershed_names:

    color = 'k'

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in ['CNR']:
        
        for sce in ['RCP2.6','RCP8.5']:
    
            ix = 1
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
        
            for simul in simul_list:
                
                fig1, axs1 = plt.subplots(1,1, figsize=(10,10))
            
                ax = axs1
                ax.set_title(mod+' / '+sce)
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                
                acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                
                # Historic
                h = 30 * 12
                acc_npy_h = list(acc_npy.items())[0:h]
                for key in range(len(acc_npy_h)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
                zero = acc_npy_h[0] * 0
                for i in range(len(acc_npy_h)):
                    tempo = acc_npy_h[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_h = zero.copy() / len(acc_npy_h)
                # ax.imshow(days_flux_h)
            
                # To look
                acc_npy = list(acc_npy.items())[-h:]
                # acc_npy = list(acc_npy.items())[h:]
                for key in range(len(acc_npy)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
                zero = acc_npy[0] * 0
                for i in range(len(acc_npy)):
                    tempo = acc_npy[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux = zero.copy() / len(acc_npy)
                
                # Anomaly
                days_flux_ano = ( (days_flux - days_flux_h) ) * 100
                
                masked = days_flux_ano
                Z = masked.flatten()
                from scipy.stats import norm
                pdf = norm.pdf(Z, Z.mean(), Z.std())
            
                print(days_flux_ano.min(), days_flux_ano.max())
                
                cmap = plt.cm.Oranges_r
                cmaplist = [cmap(i) for i in range(cmap.N)]
                cmaplist = ['darkred','orange']
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                minn = -20
                maxn = 0.1
                intn = 2.5
                bounds = np.arange(minn, maxn, intn)
                norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                pcn = ax.imshow(np.ma.masked_where(days_flux_ano >= 0, days_flux_ano),
                                cmap = cmap,
                                norm=norm, alpha=1)
                # plt.imshow(days_flux_ano)
                # plt.colorbar()
                
                cmap = plt.cm.Blues
                # cmap = plt.cm.winter_r
                cmaplist = [cmap(i) for i in range(cmap.N)]
                cmaplist = ['deepskyblue','navy']
                # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                cmap = mpl.colors.LinearSegmentedColormap.from_list(
                    'Custom cmap', cmaplist, cmap.N)
                minp = 0
                maxp = 2.1
                intp = 0.25
                bounds = np.arange(minp, maxp, intp)
                norm = mpl.colors.BoundaryNorm(bounds, cmap.N)
                pcp = ax.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano),
                                cmap = cmap,
                                norm=norm, alpha=1)
                # plt.imshow(np.ma.masked_where(days_flux_ano <= 0, days_flux_ano))
                # plt.colorbar()
                
                pc = ax.imshow(np.ma.masked_where((days_flux_ano!=0)|(days_flux_h==0),
                                                  days_flux_ano),
                                            cmap = mpl.colors.ListedColormap('forestgreen'))
                
                ax.get_xaxis().set_visible(False)
                ax.get_yaxis().set_visible(False)
                ax.axis('off')
    
                ax.imshow(line, cmap=mpl.colors.ListedColormap('k'))
                # ax.set_title(params, fontsize=8)
                plt.subplots_adjust(hspace = -0.6)
            
            position=fig1.add_axes([1,0.3,0.015,0.32])  ## the parameters are the specified position you set 
            cb = fig1.colorbar(pcp,cax=position) ##
            cb.set_ticks(np.arange(minp, maxp, intp))
            cb.set_ticklabels(np.arange(minp, maxp, intp).round(1))
            # cb.ax.invert_xaxis()
            
            position=fig1.add_axes([1.10,0.3,0.015,0.32])  ## the parameters are the specified position you set 
            cb = fig1.colorbar(pcn,cax=position) ##   
            cb.set_ticks(np.arange(minn, maxn, intn))
            cb.set_ticklabels(np.arange(minn, maxn, intn))
            
            # fig1.savefig(figsim_folder+
            #              watershed_name+'_'+mod+'_'+sce+'_'+
            #              '_anamaly'+'.png', dpi=300, bbox_inches='tight')

#%% FIG - Histogramm disribution of anomaly persistency index historic vs future

import matplotlib as mpl

watershed_names = ['Lasset']

typ = 'projec'

var = 'REC'
scan = 'outflow_drain'

for watershed_name in watershed_names:

    color = 'k'
        
    rcp26 = pd.DataFrame()
    rcp85 = pd.DataFrame()
        
    fig2, ax2 = plt.subplots(1,1, figsize=(5,4),
                            sharex=True, sharey=True)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'  # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    wbt.vector_lines_to_raster(stable_folder+'geographic/'+'watershed_contour.shp',
                               stable_folder+'geographic/'+'watershed_contour.tif',
                               base = stable_folder+'geographic/'+'watershed_dem.tif')
    line = imageio.imread(stable_folder+'geographic/'+'watershed_contour.tif')
    line = np.ma.masked_where(line < 0, line)
    
    for mod in ['CNR']:
        
        for sce in ['RCP2.6','RCP8.5']:
    
            ix = 1
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
        
            for simul in simul_list:
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                
                acc_npy = np.load(os.path.join(simul, '_watershed','accumulation_flux.npy'), allow_pickle=True).item()
                
                # Historic
                acc_npy_h = list(acc_npy.items())[0:30*12]
                for key in range(len(acc_npy_h)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy_h[key] = np.ma.masked_array(acc_npy_h[key][1], mask=(mask<0))
                zero = acc_npy_h[0] * 0
                for i in range(len(acc_npy_h)):
                    tempo = acc_npy_h[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux_h = zero.copy() / len(acc_npy_h)
                # ax.imshow(days_flux_h)
            
                # To look
                acc_npy = list(acc_npy.items())[-30*12:] # -80*12:-50*12
                # acc_npy = list(acc_npy.items())[h:]
                for key in range(len(acc_npy)):
                    # print(key)
                    mask = imageio.imread(stable_folder+'geographic/'+'watershed_dem.tif')
                    # acc = np.ma.masked_where(dem.read(1) < 0, dem.read(1))
                    acc_npy[key] = np.ma.masked_array(acc_npy[key][1], mask=(mask<0))
                zero = acc_npy[0] * 0
                for i in range(len(acc_npy)):
                    tempo = acc_npy[i].copy()
                    tempo[tempo>0] = 1
                    zero = zero + tempo
                days_flux = zero.copy() / len(acc_npy)
                
                # Anomaly
                days_flux_ano = ( (days_flux - days_flux_h) ) * 100
                data = days_flux_ano[~days_flux_ano.mask]
                
                masked = data
                # masked = days_flux_ano
                Z = masked.flatten()
                from scipy.stats import norm
                pdf = norm.pdf(Z, Z.mean(), Z.std())
                                
                if sce == 'RCP2.6':
                    color = 'dodgerblue'
                    rcp26[mod] = Z
                if sce == 'RCP8.5':
                    color = 'red'
                    rcp85[mod] = Z
    
                # import seaborn as sns
                # sns.distplot(Z, bins=100, rug = False, hist = True, kde = False, norm_hist = True,
                #       kde_kws = {'shade': True, 'linewidth': 0.5},
                #       rug_kws={"color": "k"},
                #       hist_kws={"histtype": "step", "linewidth": 1, "alpha": 1},
                #       color=color)
                
                # ax2.hist(Z, bins = 100, density=True,
                #         color = color, edgecolor = 'none')
                
                heights, edges = np.histogram(Z, bins=100, density=True)
                left_edges = edges[:-1]
                # width = 0.85*(left_edges[1] - left_edges[0])
                ax2.bar(left_edges, heights, align='edge', width=1/5,
                        lw=0, color=color, alpha=0.5)
    
    # hist26, edg26  = np.histogram(rcp26.mean(axis=1), bins=100, density=True)
    # ax2.plot(edg26[:-1], hist26, lw=1, color='dodgerblue')
    # hist85, edg85  = np.histogram(rcp85.mean(axis=1), bins=100, density=True)
    # ax2.plot(edg85[:-1], hist26, lw=1, color='red')
    
    ax2.set_xlim(-30,10)
    ax2.set_ylim(1e-3,1)
    ax2.set_title(watershed_name)
    ax2.set_yscale('log')
    ax2.set_xlabel('Persistency index anomaly [%]')
    ax2.set_ylabel('Density')
    
    # fig1.savefig(figsim_folder+
    #               watershed_name+'_'+mod+'_'+sce+'_'+
    #               '_anamaly'+'.png', dpi=300, bbox_inches='tight')
                    
#%% ----

#%% FIG : Hysteresis of discharge

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    xn = 0.1
    xx = 100
    yn = 0.1
    yx = 100
    ax = axs1
    ax.set_title(mod_list)
    ax.set_aspect('equal', adjustable='box')
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes
    axz = inset_axes(ax, width="40%", height="40%", loc='upper left',
                     bbox_to_anchor=(0.0,0,1,1), bbox_transform=ax.transAxes)
    axz.set_aspect('equal', adjustable='box')
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')
        # from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        # axz = inset_axes(ax, width="40%", # width = 30% of parent_bbox
        #                   height=1., # height : 1 inch
        #                   loc=2)
        # axz.set_aspect('equal', adjustable='box')
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                        
            Qmod = (Smod[scan] * 1000 * 30).squeeze()   # mm/months            
            Cmod = Smod['recharge'] * 1000 * 30 # mm/months

            if sce == 'historic' :
                Qmod = select_period(Qmod, 1990, 2019)
                Cmod = select_period(Cmod, 1990, 2019)
            if sce != 'historic':
                Qmod = select_period(Qmod, 2070, 2099)
                Cmod = select_period(Cmod, 2070, 2099)
            
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            hyst = Hysteresis(DFmod, simul)
            hyst.prepare_xy_raw()
            hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
            columns_x = hyst.xrecapl.columns
            columns_y = hyst.yrecapl.columns
            
            n = len(columns_x)
            cmap = cmap_dict[sce]
            cmap_color = plt.get_cmap(cmap)(np.linspace(0, 1, n))
            
            color = color_dict[sce]
            
            dfevol = hyst.dfmet.iloc[:-1]
            dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
            dfmean = hyst.dfmet.iloc[-1]
            
            for i, (colx, coly) in enumerate(zip(columns_x, columns_y)):
                data = pd.DataFrame()
                data['inx'] = hyst.xrecapl[colx]
                data['iny'] = hyst.yrecapl[coly]
                # ax.plot(data.inx, data.iny, linestyle = '-', lw=0.5, color=cmap_color[i], alpha=0.75, zorder=0)
            ax.plot(data.inx, data.iny, linestyle = '-', lw=2, color=color, zorder=1)

            # ax.scatter(hyst.x, hyst.y, c=hyst.wy, cmap=cmap_dict[sce], marker=".", 
            #            s=10, vmin=1, vmax=12, alpha=0.75, ec='none', zorder=0)
            # ax.plot(hyst.xi, hyst.yi, marker="o", markersize=9, markeredgecolor='black', 
            #         markerfacecolor='white', linestyle = 'None') 
            # for k in hyst.wyi:
            #     ax.annotate(k,(hyst.xi[k],hyst.yi[k]), family='sans-serif', fontsize=5, 
            #                 color='black', weight="bold", ha='center', va='center')
            
            for k in hyst.wyi:
                # if (k == 10) | (k == 11) | (k == 12) | (k == 1) | (k == 2) | (k == 3) | (k == 4) :
                if (k == 12) :
                    ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=0, lw=0,
                              markeredgecolor='k', markerfacecolor=color,
                              mew=0, linestyle = '-')
                    # ax.plot(hyst.xi[k], hyst.yi[k], marker="o", markersize=7,
                    #           markeredgecolor=color, markerfacecolor='white',
                    #           mew=1,
                    #           linestyle = 'None', zorder=csce+cp+cont)
                    # ax.annotate(k,(hyst.xi[k],hyst.yi[k]),
                    #               family='sans-serif', fontsize=5, 
                    #               color=color, weight="bold", ha='center', va='center',
                    #               zorder=csce+cp+cont)
                    
            # ax.xaxis.set_ticks(np.arange(xn, xx+1, 25))
            # ax.yaxis.set_ticks(np.arange(yn, xx+1, 25))
            # ax.errorbar(hyst.xi, hyst.yi,
            #             yerr=np.vstack([hyst.yi-hyst.ye.q25, hyst.ye.q75-hyst.yi]),
            #             xerr=np.vstack([hyst.xi-hyst.xe.q25, hyst.xe.q75-hyst.xi]),
            #             ecolor = 'black', fmt = 'none', capsize = 1, elinewidth=0.5, 
            #             capthick=0.5, zorder=1)
            
            polyg_loop = Polygon(tuple(hyst.data.itertuples(index=False, name=None)))
            xpolyg, ypolyg = polyg_loop.exterior.xy
            maxi = 1.5
            mini = -0.1
            line_oneone = SG.LineString([(mini,mini), (maxi,maxi)])
            areas = cut_polygon_by_line(polyg_loop, line_oneone)
            from descartes import PolygonPatch
            for i in range(len(areas)):
                ring_patch = PolygonPatch(areas[i], color=color, alpha=0.6, lw=0, ec="k", zorder=1000)
                # ax.add_patch(ring_patch)
            
            # plt.setp(axs2, xlim=(min(xmin),max(xmax)), ylim=(min(ymin),max(ymax)))
            ax.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                    linestyle='--', color='grey', linewidth=1.5, zorder=-1)

            ax.grid(color='grey',alpha=0.2)
            ax.set_ylabel('Q [mm/month]')
            ax.set_xlabel('R [mm/month]')
            
            # AX ZOOM
            axz.plot(data.inx, data.iny, linestyle = '-', lw=1, color=color, zorder=1)
            xmin, xmax = axz.get_xlim()
            ymin, ymax = axz.get_ylim()
            axz.plot(np.linspace(xn,xx,50), np.linspace(yn,yx,50), 
                    linestyle='--', color='grey', linewidth=1, zorder=-1)
            axz.set_xlim(xn,xx)
            axz.set_ylim(yn,yx)
            axz.get_xaxis().set_visible(False)
            axz.get_yaxis().set_visible(False)
            axz.set_xscale('log')
            axz.set_yscale('log')
            # axz.axis('off')
            for axis in ['top','bottom','left','right']:
                axz.spines[axis].set_linewidth(1)

    plt.tight_layout()
                        
    # fig1.savefig(figsim_folder+'hysteresis_loop'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Evolution of saturation and proportion intermittency

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
mod_list = ['NOR1']
sce_list = ['RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
scan_list = ['intermit_areas','perenn_areas']

temporal = True
space = 0
norm = False

watershed_names = ['Canut','Nancon']
watershed_names = ['Canut']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
    for mod in mod_list:
                
        fig, axs = plt.subplots(1,2, figsize=(8,3))
        axs = axs.ravel()
    
        for sce in sce_list:
            
            print(watershed_name + ' + ' + mod + ' + ' + sce)
            
            simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*')
        
            compt = 0
            
            list_max = []
            list_max_per = []
            list_max_int = []
                    
            for it, simul in enumerate(simul_list[:]):
                    
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot = max(max_per,max_int)
            
                list_max.append(max_tot)
                list_max_per.append(max_per)
                list_max_int.append(max_int)
                
            for it, simul in enumerate(simul_list[:]):
                
                ax = axs[it]
                
                model_name = simul.split('\\')[-1]
                Sy = float(model_name.split('_')[3].split('-')[0]) # %
                K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
                E = float(model_name.split('_')[3].split('-')[2]) # m
                D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
                params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
                Smod_path = simul+'/_watershed/_simulated_results.csv'            
                if not os.path.exists(Smod_path):
                    compt += 1
                    continue
                
                Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
                idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
                # Smod = Smod.set_index(idx)
                years = Smod.index.year.unique()
                
                Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
                Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
                
                Smod['year'] = Smod.index.year.values # group by month and year, get the average
                Smod['month'] = Smod.index.month.values # group by month and year, get the average
                Smod = Smod.pivot('month','year')
                
                max_per = Smod['perenn_areas'].max().max()
                max_int = Smod['intermit_areas'].max().max()
                max_tot_per = max(list_max_per)
                max_tot_per = 5
                max_tot_int = max(list_max_int) 
                max_tot_int = 20
                max_tot = max(list_max)
                max_tot = 20
                
                # fig, ax = plt.subplots(1,1, figsize=(8,5))
                from matplotlib import colors
                import matplotlib.cm as cmx
                
                for year in years[:]:
                    p = Smod[['prop_perenn','perenn_areas']]
                    i = Smod[['prop_intermit','intermit_areas']]
                                        
                    p = p.droplevel(level=0, axis=1)
                    p = p[year]
                    p.columns = ['prop_perenn','perenn_areas']
                    p = p.sort_values('prop_perenn', ascending=False)
                    p['prop_perenn'] = p.prop_perenn.cumsum() / 12
                        
                    p1 = p.prop_perenn.shift(+1)
                    p1.iloc[0] = 0
                    x1 = p1.values
                    x2 = p.prop_perenn.values
                    values = p.perenn_areas.values
                    # jet = cm = plt.get_cmap('winter_r')
                    cmaplist = ['c','deepskyblue','dodgerblue','blue','navy']
                    cmaplist = ['lightgreen','seagreen']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.kbc_r
                    # cmap = 'cool_r'
                    jet = cm = plt.get_cmap(cmap)
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_per)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1.1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ##
                            cb.set_label('Saturation [%]', rotation=270, labelpad=30)
                        
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)  
                        start = x
                        endp = y
                        width = endp-start
                        ax.bar(x = year, height=width, bottom=start, width=1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    i = i.droplevel(level=0, axis=1)
                    i = i[year]
                    i.columns = ['prop_intermit','intermit_areas']
                    i = i.sort_values('prop_intermit', ascending=True)
                    i['prop_intermit'] = i.prop_intermit.cumsum() / 12
                    
                    i1 = i.prop_intermit.shift(+1)
                    i1.iloc[0] = 0
                    i1 = i1 + endp
                    x1 = i1.values
                    x2 = i.prop_intermit.values + endp
                    values = i.intermit_areas.values
                    # jet = cm = plt.get_cmap('autumn_r')
                    cmaplist = ['darkred','red','orangered','orange']
                    cmaplist = ['saddlebrown','moccasin']
                    import colorcet as cc
                    # cmaplist[-1] = (.5, .5, .5, 1.0) # first value
                    cmap = mpl.colors.LinearSegmentedColormap.from_list(
                        'Custom cmap', cmaplist)
                    cmap = cc.cm.fire_r
                    # cmap = 'Wistia'
                    jet = cm = plt.get_cmap(cmap) 
                    cNorm  = colors.Normalize(vmin=0, vmax=max_tot_int)
                    scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=jet)
                    if year == 2020:
                        if it==1:
                            position=fig.add_axes([1,0.3,0.02,0.35])  ## the parameters are the specified position you set 
                            cb = fig.colorbar(scalarMap,cax=position) ## 
            
                    for idx, x, y in zip(values, x1, x2):          
                        colorVal = scalarMap.to_rgba(idx)
                        start = x
                        endi = y
                        width = endi-start
                        ax.bar(x = year, height = width, bottom=start, width = 1,
                                label = str(idx), color=colorVal, lw=0)
                    
                    ax.set_ylim(0,1)
                    bal = ((i.prop_intermit.sum()) + (p.prop_perenn.sum())).sum()
                    min_max = [2020, 2099]
                    ax.set_xlim(min_max)
                    ax.set_xticks(np.arange(min_max[0], min_max[1]+2, 20.0))
                    tox = np.arange(min_max[0], min_max[1]+2, 20.0).astype(int)
                    ax.set_xticklabels(tox)
                    
                    if ((it) == 0) | ((it) == 3) | ((it) == 6):
                        ax.set_ylabel('Proportion of network')
                                 # ax.set_ylabel('$Eccent_{ratio}$ [-]')
                    if ((it) == 6) | ((it) == 7) | ((it) == 8):
                        ax.set_xlabel('Date')
                        
                    x_ticks = ax.xaxis.get_major_ticks()
                    x_ticks[0].label1.set_visible(False) ## set first x tick label invisible
                    x_ticks[-1].label1.set_visible(False)
                    
            # plt.tight_layout()
            
            # fig1.savefig(figsim_folder+'matrix_evol_'+sce+'.png',
            #               dpi=300, bbox_inches='tight', transparent=True)

#%% FIG : Boxplot of discharge

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['grey',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

scan_list = ['surflow_areas','perenn_areas','intermit_areas']
bxlim = (0.5,3.5)
sce_pos = ["1","2","3"]
pos_dict = dict(zip(sce_list, sce_pos))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(9,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

metric = 'qmean'

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2010)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan]
        if scan == 'outflow_drain':
            Qmod = Qmod * 1000 # mm/months
            Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        # hyst = Hysteresis(DFmod, simul)
        # hyst.prepare_xy_raw()
        # hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        # columns_x = hyst.xrecapl.columns
        # columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        # dfevol = hyst.dfmet.iloc[:-1]
        # dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        # dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
        # ax.set_title(params, fontsize=8)
        # fig3.suptitle(metric.upper(), y=0.98)
        boxprops = dict(linestyle='-', linewidth=1, color='black',
                        facecolor=color)
        medianprops = dict(linestyle='-', linewidth=1, color='black')
        meanpointprops = dict(markersize=3, marker='o', markeredgecolor='black',
                              markerfacecolor='black', linestyle='-')
        
        if sce !='historic':
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2020)&(Qmod.index.year<2060)],
                            positions=[int(pos_dict[sce])-0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
            bp = ax.boxplot(Qmod[(Qmod.index.year>=2060)&(Qmod.index.year<2100)],
                            positions=[int(pos_dict[sce])+0.1],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
            for element in bp['whiskers']:
                element.set_color('k')
                element.set_linestyle('-')
        else:
            bp = ax.boxplot(Qmod, positions=[int(pos_dict[sce])],
                              whis=True, showfliers=False, showmeans=True,
                              medianprops=medianprops, meanprops=meanpointprops,
                              patch_artist=True, boxprops=boxprops)
        for element in bp['whiskers']:
            element.set_color('k')
            element.set_linestyle('-')

        # ax.scatter(int(pos_dict[sce]), Qmod.min(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]), Qmod.max(), marker='.',color='dimgrey',s = 3)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()-Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        # ax.scatter(int(pos_dict[sce]),
        #             Qmod.mean()+Qmod.std(),
        #             marker='_',color='dimgrey',s = 7, zorder=2)
        
        ax.set_xticks(np.arange(1,len(sce_list)+1,1))
        # ax.set_xticklabels([x.upper() for x in sce_list], fontsize=10)
        # bmin.append(Qmod.min())
        # bmax.append(Qmod.max())
        # plt.setp(axs3, ylim=(min(bmin),max(bmax)))
        ax.set_ylim(-0.1,2.5)
        # ax.set_xlim(bxlim)
        plt.tight_layout()

        # if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
        #     ax.set_xlabel('Date')
        
        # ord_min.append(q25.min())
        # ord_max.append(q75.max())
        # plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        # plt.setp(axs, ylim=(0.05,3))
        

plt.tight_layout()

fig1.savefig(figsim_folder+'boxplot_discharge'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Intermensual of discharge

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

sim_state='transient'
time_step = 'M'
mod = 'NOR1'
typ = 'projnor'
var = 'REC'
scan = 'outflow_drain'
sce_list = ['historic','RCP2.6','RCP8.5']
# sce_list = ['historic']
sce_cmap = ["Blues","Reds"]
sce_color = ['k',"dodgerblue","red"]

cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

temporal = True
space = -10
norm = False

fig1, axs = plt.subplots(3,3, figsize=(10,9))
axs = axs.ravel()
xmin = []
xmax = []
ymin = []
ymax = []
            
compt = 1

f = 2020
l = 2099

simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    
ord_min = []
ord_max = []

for ix in np.arange(1,9+1,1):
    # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*')
    
    ax = axs[ix-1]
    # ax.set_aspect('equal', adjustable='box')
    
    csce = 20
    for sce in sce_list:
        if sce == 'historic':
            simul = glob.glob(simulations_folder+'*'+typ+'_'+str(ix)+'*'+'RCP8.5'+'*')[0]
        
        # simul_list = glob.glob(simulations_folder+'*'+typ+'_'+str(i)+'*'+sce+'*')
        else:
            simul = glob.glob(simulations_folder+typ+'_'+str(ix)+'*'+sce+'*')[0]
        print(simul)
        
        print(sce)

        model_name = simul.split('\\')[-1]
        Sy = float(model_name.split('_')[3].split('-')[0]) # %
        K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
        E = float(model_name.split('_')[3].split('-')[2]) # m
        D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
        params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
        Smod_path = simul+'/_watershed/_simulated_results.csv'            
        if not os.path.exists(Smod_path):
            compt += 1
            continue
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = 'historic',
                                                 first_year = 1960, last_year = 2010,
                                                 time_step = time_step, sim_state=sim_state)
        Hist = BV.forcing.recharge
        BV.forcing.update_recharge_surfex(clim_mod = mod, clim_sce = sce,
                                          first_year = 1960, last_year = 2099, 
                                          time_step = time_step, sim_state=sim_state)
        BV.forcing.update_recharge(BV.forcing.recharge, sim_state=sim_state)
        Rech = BV.forcing.recharge # m/month
        if (sce == 'RCP2.6') | (sce == 'RCP8.5'):
            Rech = pd.concat((Rech, Hist), axis=1).mean(axis=1)
            BV.forcing.update_recharge(Rech, sim_state=sim_state)
            Rech = BV.forcing.recharge # m/month
            
        # idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
        # Smod = Smod.set_index(idx)
        if sce == 'historic':
            Smod = select_period(Smod, 1960, 2005)
        else:
            Smod = select_period(Smod, f, l)
        
        Smod.recharge = Rech
        
        Qmod = Smod[scan] 
        Qmod = Qmod * 1000 # mm/months
        Qmod = Qmod.squeeze()    
        Cmod = Smod['recharge'] * 1000 # mm/months
        DFmod = pd.DataFrame(columns=['x','y'])
        DFmod['x'] = Cmod
        DFmod['y'] = Qmod
        first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
        last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
        DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 10:
                DFmod = DFmod[idx:]   
                break
        DFmod = DFmod.sort_index(ascending=False)
        for idx in range(len(DFmod)):
            if DFmod.index[idx].month == 9:
                DFmod = DFmod[idx:]
                break
        DFmod = DFmod.sort_index(ascending=True)
        
        hyst = Hysteresis(DFmod, simul)
        hyst.prepare_xy_raw()
        hyst.compute_xy_metrics(temporal=temporal, space=space, norm=norm)
        columns_x = hyst.xrecapl.columns
        columns_y = hyst.yrecapl.columns
        
        color = color_dict[sce]
        print(color)
        
        dfevol = hyst.dfmet.iloc[:-1]
        dfevol = dfevol.set_index(pd.to_datetime(dfevol.index, format='%Y'))
        dfmean = hyst.dfmet.iloc[-1]

        ################ FIG 2 ################
                       
        # ax = axs2
        # ax.set_title(params, fontsize=8)
        # fig2.suptitle(metric.upper(), y=0.98)
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        
        mean = hyst.y.groupby([lambda x: x.month]).mean()
        mean = mean.append(mean.iloc[[0]])
        mean.index = np.arange(1,14,1)
        q25 = hyst.y.groupby([lambda x: x.month]).quantile(0.25)
        q25 = q25.append(q25.iloc[[0]])
        q25.index = np.arange(1,14,1)
        q75 = hyst.y.groupby([lambda x: x.month]).quantile(0.75)
        q75 = q75.append(q75.iloc[[0]])
        q75.index = np.arange(1,14,1)
        
        # if scan == 'perenn_areas':
        #     alpha=0.5
        ax.plot(mean, color=color, lw=2)
        ax.fill_between(mean.index, q25, q75, alpha=0.2, color=color,
                          linewidth=0)
        xticks = np.arange(1,13+1,1)
        mois = ['J','F','M','A','M','J','J','A','S','O','N','D','J']
        ax.set_xticks(xticks)
        ax.set_xticklabels(mois, minor=False, rotation='horizontal', fontsize=13)
        ax.set_xlim(1,13)
        
        ax.set_yscale('log')
        # ax.fill_between(dfevol.index, dfevol.q10, dfevol.q90, linestyle = '-',
        #                  lw=0, color=color, alpha=0.25)
        # ax.plot(dfevol.qmean, linestyle = '-', lw=2, color=color,
        #         zorder=1)

        # ax.plot(dfevol[dfevol.index.year<=2021][metric], linestyle = '-', lw=3, color='k',
        #         zorder=40)
        
        # metric = 'excent'
        # ax.plot(dfevol[metric], dfevol.index, linestyle = '-', lw=2, color=color,
        #         zorder=1)
        # metric1 = 'slope'
        # metric2 = 'slope_abs'
        # ax.plot(dfevol[metric1]/dfevol[metric2], dfevol.index, linestyle = '-', lw=2, color='pink',
        #         zorder=1)
        
        # ax.set_xscale('log') 
        # ax.axhline(1, linestyle = '--', lw=2, color='grey', zorder=0)
        # ax.set_xlim(-10,100)
        # ax.set_ylim(1,8)
        
        
        # years_maj = YearLocator(40)   # every x year
        # # years_min = YearLocator(1)
        # years_maj_fmt = DateFormatter('%Y')
        # # months_maj = MonthLocator(6)  # every x month
        # # months_min = MonthLocator(3)
        # # months_maj_fmt = DateFormatter('%m') #b = name of month ?
        # ax.xaxis.set_major_locator(years_maj)
        # # ax.xaxis.set_minor_locator(years_min)
        # ax.xaxis.set_major_formatter(years_maj_fmt)
        # # ax.set_ylim(0,40)
        # ymin.append(dfevol.index.year.min())
        # ymax.append(dfevol.index.year.max())
        # xmin.append(dfevol[metric].min())
        # xmax.append(dfevol[metric].max())
        # ax.set_xlim(pd.to_datetime(str(1960-space)),pd.to_datetime(str(2100+1)))
        
        
        # ax.set_ylim(0.5,4)
        # ax.set_ylim(0,25)
        plt.tight_layout()
        # ax.set_yticks(np.arange(1,4+1,1))
        # ax.set_yticklabels(np.arange(1,4+1,1))
        # ax.set_yticks(np.arange(5,25+1,5))
        # ax.set_yticklabels(np.arange(5,25+1,5))
        # ax.invert_yaxis()
        # ax.grid('grey')
        
        if ((ix-1) == 0) | ((ix-1) == 3) | ((ix-1) == 6):
            ax.set_ylabel('Q [mm/month]')
            # ax.set_ylabel('$Eccent_{ratio}$ [-]')
        if ((ix-1) == 6) | ((ix-1) == 7) | ((ix-1) == 8):
            ax.set_xlabel('Date')
        
        ord_min.append(q25.min())
        ord_max.append(q75.max())
        plt.setp(axs, ylim=(min(ord_min),max(ord_max)))
        plt.setp(axs, ylim=(0.05,3))

plt.tight_layout()

fig1.savefig(figsim_folder+'intermensual_discharge'+'.svg', dpi=300, bbox_inches='tight')
fig1.savefig(figsim_folder+'intermensual_discharge'+'.png', dpi=300, bbox_inches='tight')

#%% FIG : Time anomaly evolution historic vs future 

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['historic','RCP2.6','RCP8.5']
sce_cmap = ["Greys","Greens","Reds"]
sce_color = ['k',"dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = True
space = -10
norm = False

watershed_names = ['Canut','Nancon']

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(8,3))
    ax = axs1
    
    for mod in mod_list:
            
        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]

            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            
            idx = pd.date_range(start='01/01/2000', end='31/12/2099', freq='M')
            # Smod = Smod.set_index(idx)
            years = Smod.index.year.unique()
            
            Smod['prop_perenn'] = Smod['perenn_areas'] / Smod['surflow_areas']
            Smod['prop_intermit'] = Smod['intermit_areas'] / Smod['surflow_areas']
            Smod['prop_ratio'] = Smod['prop_intermit'] / Smod['prop_perenn']
            
            Smod['year'] = Smod.index.year.values # group by month and year, get the average
            Smod['month'] = Smod.index.month.values # group by month and year, get the average
            # Smod = Smod.pivot('month','year')
            
            # ax.plot(Smod.surflow_areas)
            
            max_per = Smod['perenn_areas'].max().max()
            max_int = Smod['intermit_areas'].max().max()
            max_tot = max(max_per,max_int)
        
            intm = select_period(Smod, 1960,2021)
            intm = intm.groupby([lambda x: x.month]).mean()
            
            list_max.append(max_tot)
            
            for i in intm.month.values:
                Smod.loc[Smod.index.month==i, 'ano_prop_ratio'] = Smod.loc[Smod.index.month==i,'prop_ratio'] \
                                                                  - intm.loc[intm.month==i,'prop_ratio'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_intermit_areas'] = Smod.loc[Smod.index.month==i,'intermit_areas'] \
                                                                  - intm.loc[intm.month==i,'intermit_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_perenn_areas'] = Smod.loc[Smod.index.month==i,'perenn_areas'] \
                                                                  - intm.loc[intm.month==i,'perenn_areas'].values[0]
                Smod.loc[Smod.index.month==i, 'ano_surflow_areas'] = Smod.loc[Smod.index.month==i,'surflow_areas'] \
                                                                  - intm.loc[intm.month==i,'surflow_areas'].values[0]                   
            col = 'ano_prop_ratio'
            ax.set_ylim(-1,1)
            ax.set_ylabel('Anomaly')
            ax.set_xlabel('Date')
    
            plus = Smod[col][Smod[col] >= 0]
            minus = Smod[col][Smod[col] < 0]
            
            color = color_dict[sce]
            
            if sce == 'historic':
                zorder = 10
                Smod = select_period(Smod, 1990, 2021)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            else:
                zorder = 0
                Smod = select_period(Smod, 2021, 2099)
                Smod = Smod.resample('Y').mean()
                Smod = Smod.rolling(window=10).mean()#.shift(-10)
            
            ax.plot(Smod[col], color=color, zorder=zorder)
            ax.axhline(y=0, c='k')
            ax.set_xlim(pd.to_datetime(str(1990)),pd.to_datetime(str(2100)))
            plt.xticks(rotation='horizontal')
            plt.xlabel('Date')
            ax.axvspan(pd.to_datetime(str(1990)), pd.to_datetime(str(2021)), color='lightgrey', alpha=0.1, zorder=0)

            years = mdates.YearLocator(20)   # every year
            yearsmin = mdates.YearLocator(1)
            years_fmt = mdates.DateFormatter('%Y')
            months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            ax.xaxis.set_major_locator(years)
            ax.xaxis.set_minor_locator(yearsmin)
            ax.xaxis.set_major_formatter(years_fmt)
            
plt.tight_layout()

# fig1.savefig(figsim_folder+'evolution_intermitperenn'+'.svg', dpi=300, bbox_inches='tight')

#%% FIG : Relation between recharge/discharge and intermittency 

from scipy.stats import binned_statistic

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['RCP2.6','RCP8.5']
sce_list = ['RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# x_name = 'outflow_drain'
x_name = 'recharge'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
xmin = []
xmax = []
ymin = []
ymax = []

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    xn = 1e-6
    xx = 1e-2
    yn = 1e-3
    yx = 1e1
    ax = axs1
    ax.set_title(mod_list)
    # ax.set_aspect('equal', adjustable='box')
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            if sce == 'historic':
                Smod = select_period(Smod, 1960, 2005)
            else:
                Smod = select_period(Smod, 2020, 2099)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
            
            ax = axs1
            # ax.set_aspect('equal', adjustable='box')
            # ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
            #            s=30, alpha=0.5)
            
            if sce == 'RCP2.6':
                color = 'dodgerblue'
            if sce == 'RCP8.5':
                color = 'red'
            
            ax.scatter(Smod[x_name],
                       (Smod[y_name]),
                       c=Smod.index.month, ec='none',
                        s=30, alpha=0.5)
            
            if y_name == 'outflow_drain':
                ax.set_yscale('log')
                x = Smod[x_name]
                y = Smod[y_name]
                y[y==0] = 0.001
                x = np.log10(x)
                y = np.log10(y)
                maxim = max(max(x),max(y))
                minim = min(min(x),np.nanmin(y[y != -np.inf]))
                s, edges, _ = binned_statistic(x, y, statistic='mean',
                                               bins=np.geomspace(minim,maxim,25))
                the_x = edges[:-1]+np.diff(edges)/2
                the_y = s.copy()
                ax.scatter(10**the_x, 10**the_y, c="white", zorder=3)       
            
            if y_name == 'prop_ratio':
                ax.set_yscale('log')
                
                x = Smod[x_name]
                y = Smod[y_name]
                y[y==0] = 0.001
                # x = np.log(x)
                # y = np.log(y)
                maxim = max(max(x),max(y))
                minim = min(min(x),np.nanmin(y[y != -np.inf]))
                s, edges, _ = binned_statistic(x, y, statistic='mean',
                                               bins=np.geomspace(minim,maxim,25))
                the_x = edges[:-1]+np.diff(edges)/2
                the_y = s.copy()
                ax.scatter(the_x, the_y, c="white", zorder=3)  
            
            # ax.scatter(Qmod, Smod.surflow_areas, color=color, ec='none',
            #            s=30, alpha=0.5)
                        
            ax.grid(color='grey',alpha=0.2)
                
            plt.tight_layout()
            
            ax.set_xlabel(x_name)
            ax.set_ylabel(y_name)
            
            ax.set_xscale('log')
            
            xmin.append(Smod[x_name].min())
            xmax.append(Smod[x_name].max())
            ymin.append(Smod[y_name].min())
            ymax.append(Smod[y_name].max())
            
            if xn == []:
                plt.setp(ax,
                         xlim=(min(xmin),max(xmax)),
                         ylim=(min(ymin),max(ymax)))
            else:
                ax.set_xlim(xn,xx)
                ax.set_ylim(yn,yx)
            
    fig1.tight_layout()
    # fig1.savefig(figsim_folder+'relation_qall'+'.png', dpi=300, bbox_inches='tight')

#%% FIG : Pdf proportion of intermittency vers perennial part

from scipy.stats import binned_statistic

figsim_folder = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/PHD/8_paper/hysteresis/figures/_outputs/'

# Things
typ = 'proj1'
time_step = 'M'
sim_state = 'transient'
var = 'REC'
scan = 'outflow_drain'

# Colored
mod_list = ['NOR1','IPS1']
sce_list = ['RCP2.6','RCP8.5']
# sce_list = ['RCP8.5']
sce_cmap = ["Greens","Reds"]
sce_color = ["dodgerblue","red"]
cmap_dict = dict(zip(sce_list, sce_cmap))
color_dict = dict(zip(sce_list, sce_color))

# Hysteres
temporal = False
space = 0
norm = False

watershed_names = ['Canut','Nancon']

# y_name = 'seepage_areas'
y_name = 'surflow_areas'
# y_name = 'intermit_areas'
# y_name = 'prop_ratio'
# y_name = 'perenn_areas'
# y_name = 'outflow_drain'
# y_name = 'groundwater_storage'
xmin = []
xmax = []
ymin = []
ymax = []

fig1, axs1 = plt.subplots(1,1, figsize=(5,4))
xn = [] #1e-6
xx = 1e-2
yn = 1e-3
yx = 1e1
ax = axs1
# ax.set_aspect('equal', adjustable='box')

# fig2, ax2 = plt.subplots(1,1, figsize=(5,4))

for watershed_name in watershed_names :
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots
    color = 'k'
    
    # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
    # xn = [] #1e-6
    # xx = 1e-2
    # yn = 1e-3
    # yx = 1e1
    # ax = axs1
    # ax.set_title(watershed_name+' '+' + '.join(mod_list))
    # # ax.set_aspect('equal', adjustable='box')
    
    if watershed_name == 'Canut':
        color = 'green'
    if watershed_name == 'Nancon':
        color = 'darkmagenta'
    
    for mod in mod_list:
        
        # fig1, axs1 = plt.subplots(1,1, figsize=(5,5))
        # xn = 0.1
        # xx = 100
        # yn = 0.1
        # yx = 100
        # ax = axs1
        # ax.set_title(mod)
        # ax.set_aspect('equal', adjustable='box')

        for sce in sce_list:
            
            # if sce == 'RCP2.6':
            #     color = 'dodgerblue'
            # if sce == 'RCP8.5':
            #     color = 'red'
            
            if sce != 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+sce+'*')
                simul = simul_list[0]
            
            if sce == 'historic':
                simul_list = glob.glob(simulations_folder+typ+'*'+mod+'*'+'RCP8.5'+'*')
                simul = simul_list[0]
                
            model_name = simul.split('\\')[-1]
            Sy = float(model_name.split('_')[3].split('-')[0]) # %
            K = float(model_name.split('_')[3].split('-')[1]) / 30 / 24 / 3600 # m/s
            E = float(model_name.split('_')[3].split('-')[2]) # m
            D = "{:.1e}".format((K * E) / (Sy/100)) # m2/s
            params = 'K='+"{:.1e}".format(K)+'m/s - '+'Sy='+str(Sy)+'% - '+'D='+str(D)+'m²/s'
            Smod_path = simul+'/_watershed/_simulated_results.csv'            
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Smod['prop_ratio'] = Smod.intermit_areas / Smod.perenn_areas
            
            if sce == 'historic':
                Smod = select_period(Smod, 1960, 2005)
            else:
                Smod = select_period(Smod, 2020, 2099)
            
            Qmod = Smod[scan] 
          
            Qmod = Qmod # mm/months
            Qmod = Qmod.squeeze()    
            Cmod = Smod['recharge'] # mm/months
            DFmod = pd.DataFrame(columns=['x','y'])
            DFmod['x'] = Cmod
            DFmod['y'] = Qmod
            first_valid_loc = DFmod[DFmod.index.month==10].apply(lambda col: col.first_valid_index()).max().year
            last_valid_loc = DFmod[DFmod.index.month==9].apply(lambda col: col.last_valid_index()).min().year
            DFmod = select_period(DFmod, first_valid_loc, last_valid_loc)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 10:
                    DFmod = DFmod[idx:]   
                    break
            DFmod = DFmod.sort_index(ascending=False)
            for idx in range(len(DFmod)):
                if DFmod.index[idx].month == 9:
                    DFmod = DFmod[idx:]
                    break
            DFmod = DFmod.sort_index(ascending=True)
                        
            ax = axs1
            # ax.set_aspect('equal', adjustable='box')
            # ax.scatter(Qmod, Smod.seepage_areas, color='grey', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.surflow_areas, color='k', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.perenn_areas, color='dodgerblue', ec='none',
            #            s=30, alpha=0.5)
            # ax.scatter(Qmod, Smod.intermit_areas, color='darkorange', ec='none',
            #            s=30, alpha=0.5)
                        
            Z = Smod[y_name]
            from scipy.stats import norm
            pdf = norm.pdf(Z, Z.mean(), Z.std())
            # ax.scatter(Z, pdf, s=1, color=color)
            
            import seaborn as sns
            sns.distplot(Z, hist = False, kde = True, norm_hist = True,
                  kde_kws = {'shade': False, 'linewidth': 2},
                  color=color)
            
            # ax.hist(Z, bins = 100, density=True,
            #         color = color, edgecolor = 'none')
                        
            ax.grid(color='grey',alpha=0.2)
                
            plt.tight_layout()
            
            ax.set_xlabel(y_name)
            ax.set_ylabel('PDF')
            
            # ax.set_xscale('log')
            
            xmin.append(Z.min())
            xmax.append(Z.max())
            ymin.append(pdf.min())
            ymax.append(pdf.max())
                        
            # if xn == []:
            #     plt.setp(ax,
            #              xlim=(min(xmin),max(xmax)),
            #              ylim=(min(ymin),max(ymax)))
            # else:
            #     ax.set_xlim(xn,xx)
            #     ax.set_ylim(yn,yx)
            
    fig1.tight_layout()
    # fig1.savefig(figsim_folder+'relation_qall'+'.png', dpi=300, bbox_inches='tight')

#%% ----

#%% NOTES
