# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Libraries installed by default
import sys
import glob
import os
import fnmatch
import random
import pickle
from datetime import datetime
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Librairies to check, needed in hydromodpy modules
import shutil
from geopy.geocoders import Nominatim

# Libraries added from 'conda install' procedure
import geopandas as gpd
import matplotlib as mpl        # install automatically by geopandas
import matplotlib.pyplot as plt
from matplotlib import cm
import matplotlib.pylab as pl
import matplotlib.dates as mdates
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable

# Libraries added from 'conda forge' procedure
from osgeo import gdal, osr # or import gdal
import rasterio

# # Libraries added from 'pip install' procedure
import deepdish as dd
import flopy
import imageio
import vedo
import hydroeval
import xarray	
import netCDF4
import matplotlib_scalebar	
import contextily
import pyproj # uninstall before install
import selenium
import shapefile # named pyshp for install
import jupyter
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% ROOT

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)

cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    # print("Root path directory is: {0}".format(cwd))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

example_path = root_dir + "/examples/02_hydrographic network in steady state/"
data_path = example_path + "data/"
out_path = 'C:/Users/ronan/Documents/SIMULATIONS/HYDROMODPY/'
# out_path = '/home/agauvain/Documents/HydroModPy/'
# out_path = '...'

#%% ---- WATERSHED

#%% OPTIONS

dem_path = data_path + 'regional dem.tif'
load = True
watershed_name = 'Canut'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
modflow_path = os.path.join(root_dir,'bin/')
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

# load = True
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=bottom_path, # path
                              modflow_path=modflow_path, 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% DATA

if from_dem == None:
    # Clip specific data at the catchment scale
    BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
    BV.add_hydrography(data_path, types_obs=['regional stream network'])
    BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
    BV.add_intermittency(data_path, 'regional onde stations.shp')
    # BV.add_piezometry()

    # Extract some subbasin from data available above
    BV.add_subbasin(data_path+'additionnal/')

# General plot of the study site
if from_dem == None:
    visualization_watershed.watershed_local(dem_path, BV)
    visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% ---- RECHARGE

#%% CASES

# # Necessary to set model parameters
BV.add_climatic()

BV.climatic.update_recharge_reanalysis(path_file=data_path+'_climate_REANALYSIS.csv',
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2019,
                                       time_step='D',
                                       sim_state='transient')
BV.climatic.update_runoff_reanalysis(path_file=data_path+'_climate_REANALYSIS.csv',
                                     clim_mod='REA',
                                     clim_sce='historic',
                                     first_year=1990,
                                     last_year=2019,
                                     time_step='D',
                                     sim_state='transient')

fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge.resample('Y').sum()*1000
r = BV.climatic.runoff.resample('Y').sum()*1000
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('[mm/year]')
ax.legend()

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True
# sim_state = 'transient' # 'steady' or 'transient'
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False

# Climatic settings
recharge = pd.Series([10,20,30,40,50,60,60,50,40,30,20,10])/30/1000
first_clim = 'mean' # or 'first or value

# Hydraulic settings
nlay = 5
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]],
                  #      [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 10 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

########## LOOP ##########
list_hyd_cond = np.geomspace(1e-8,1e-3,10) * 24 * 3600 # m/day

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'domain' # or watershed

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

# Particle tracking settings
BV.settings.update_input_particules(zone_partic=zone_partic)

#%% ---- MODELING

#%% MODFLOW

iD_set_simulations = 'explorK_test1'

list_model_name = []
list_success_modflow = []
list_model_modflow = []

for hyd_cond in list_hyd_cond:
    BV.hydraulic.update_hyd_cond(hyd_cond)
    
    model_name = iD_set_simulations+'_'+str(round(hyd_cond,3))
    BV.settings.update_model_name(model_name)
    print(model_name)
    
    model_modflow = BV.preprocessing_modflow()
    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
    
    list_model_name.append(model_name)
    list_success_modflow.append(success_modflow)
    list_model_modflow.append(model_modflow)

dictio = {}
dictio['list_model_name'] = list_model_name
dictio['list_success_modflow'] = list_success_modflow
dictio['list_model_modflow'] = list_model_modflow
h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
    
dd.io.save(h5file, dictio)

#%% RELOAD

h5file = simulations_folder+'/'+'results_listing_'+iD_set_simulations
d = dd.io.load(h5file)
list_model_name = d['list_model_name'][:]
list_success_modflow = d['list_success_modflow'][:]
list_model_modflow = d['list_model_modflow'][:]

#%% POSTPROCESSING

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    if success_modflow == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth= True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          actual_date=True, 
                                                          subbasin_results=True) # or None

#%% ---- PLOT

#%% CROSS

compt = 1

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    dem_data = imageio.imread(BV.geographic.watershed_dem)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    wt_data = imageio.imread(model_modflow.tifs_file+'/watertable_elevation_t(0).tif')
    wt_data = np.ma.masked_where(wt_data < 0, wt_data)
    
    river_data = imageio.imread(stable_folder+'/hydrography/'+'regional stream network.tif')

    xvalues = np.linspace(-1,1,dem_data.shape[1])
    yvalues = np.linspace(-1,1,dem_data.shape[0])
    xx, yy = np.meshgrid(xvalues,yvalues)
    
    cur_x = dem_data.shape[1] /2
    # cur_y = dem_data.shape[0] /2
    
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof<0] = np.nan
    dem_v_plot = dem_prof[:,int(cur_x)]
    dem_v_plot[dem_v_plot == 0] = np.nan

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof<0] = np.nan
    wt_v_plot = wt_prof[:,int(cur_x)]
    wt_v_plot[wt_v_plot == 0] = np.nan

    # wt_prof_min = wt_data.astype(float)
    # wt_prof_min[wt_prof_min<0] = np.nan
    # wt_v_plot_min = wt_prof_min[:,int(cur_x)]
    # wt_v_plot_min[wt_v_plot_min == 0] = np.nan
    
    # Facecolor watertable
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                                dem_v_plot-30, wt_v_plot,
                                color='dodgerblue', alpha=0.5, lw=0)
    # Line watertable
    w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)
    
    # Facecolor unsaturated
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 
                                wt_v_plot, dem_v_plot,
                                color='saddlebrown', alpha=0.5, lw=0)
    
    # Line unsaturated
    d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
    
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_v_plot-30,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-30, color='dimgray', lw=1.5)
    
    # Settings
    ax.set_xlim(1000, 4000)
    ax.set_ylim(85, 130)
    ax.set_yticks([90,100,110,120,130])
    ax.set_xlabel('Distance [m]')
    ax.set_ylabel('Elevation [m]')
    ax.set_title('K = '+'{:.2e}'.format(model_modflow.hyd_cond.mean()/24/3600)+' m/s')
    
    compt += 1
    
    fig.tight_layout
    
    fig.savefig(os.path.join(model_modflow.figure_file,
                'CROSS_'+model_name+'_'+str(compt)+'.png'),
                bbox_inches='tight')
        
    fig.savefig(os.path.join(model_modflow.save_fig,
                'CROSS_'+model_name+'_'+str(compt)+'.png'),
                bbox_inches='tight')
    
#%% MAP

compt = 0

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):

    fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

    dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
    dem_data = np.ma.masked_where(dem_data < 0, dem_data)
    
    contour = imageio.imread(BV.geographic.watershed_contour_tif)
    contour = np.ma.masked_where(contour < 0, contour)
    
    obs_river_data = imageio.imread(stable_folder+'/hydrography/'+'regional stream network.tif')
    obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)
    
    seep_river_data = imageio.imread(model_modflow.tifs_file+'/seepage_areas_t(0).tif')
    seep_river_data = np.ma.masked_where(seep_river_data <= 0, seep_river_data)
    
    sim_river_data = imageio.imread(model_modflow.tifs_file+'/accumulation_flux_t(0).tif')
    sim_river_data = np.ma.masked_where(sim_river_data <= 0, sim_river_data)
    
    im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
    im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
    im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
    im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7)
    im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7)

    ax.set_xlabel('X [pixels]')
    ax.set_ylabel('Y [pixels]')
    ax.set_title('K = '+'{:.2e}'.format(model_modflow.hyd_cond.mean()/24/3600)+' m/s')
    
    compt += 1
    
    fig.tight_layout()

    fig.savefig(os.path.join(model_modflow.figure_file,
                'MAP_'+model_name+'_'+str(compt)+'.png'),
                bbox_inches='tight')
    
    fig.savefig(os.path.join(model_modflow.save_fig,
                'MAP_'+model_name+'_'+str(compt)+'.png'),
                bbox_inches='tight')
    
#%% GRAPH

fig, ax = plt.subplots(1, 1, figsize=(4,3), dpi=300)

for model_name, success_modflow, model_modflow in zip(list_model_name,
                                                      list_success_modflow,
                                                      list_model_modflow):
    
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'
    
    simul_csv = pd.read_csv(simulations_folder+model_name+
                            '/_postprocess/_timeseries/'+'_simulated_timeseries.csv',
                            sep=';')
    
    ax.plot(model_modflow.hyd_cond.mean()/24/3600,
            simul_csv['seepage_areas'],
            marker='o', ms=8, lw=0, color='k')
    
    ax.set_xscale('log')
    ax.set_xlabel('K [m/s]')
    ax.set_ylabel('Area saturated [%]')
    
    plt.tight_layout()
    
    fig.savefig(os.path.join(model_modflow.save_fig,
                'GRAPH_sat_'+iD_set_simulations+'.png'),
                bbox_inches='tight')

#%% ---- NOTES

os.chdir(root_dir)
