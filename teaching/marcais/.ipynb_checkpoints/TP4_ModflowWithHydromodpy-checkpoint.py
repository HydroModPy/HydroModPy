#!/usr/bin/env python
# coding: utf-8

#%% 1. Load libraries


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
# Libraries installed from the pip procedure
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


#%% 2. Complete your personal paths where hydromodpy sources are


# Fill in the directory where Hydromodpy codes are
root_dir = '/home/jean.marcais/Modeles/hydromodpy/HydroModPy-dev0.1/'
#root_dir = 'C:/Users/ronan/GitHub/Repository/HydroModPy-dev0.1/'
# Add to the path the Hydromodpy directory to recognize HydroModpy functions, classes, etc.
sys.path.append(root_dir)
# Define the directory where the notebook is stored as the current working directory
cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
    print("Root path directory is: {0}".format(cwd))


#%% Import the hydromodpy source files

import src # import the folder src from HydroModpy codes
import importlib # 
importlib.reload(src)
# import all the classes necessary to extract the watershed from Hydromodpy source files.
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large


#%% Complete the paths where data are

# complete the data paths
teaching_path = root_dir + "/teaching/marcais/"
data_path = teaching_path + "/data/"
# complete where modflow sources are
modflow_path = os.path.join(root_dir,'bin/')


#%% 3. Geographic Analysis

# in the data folder, complete the DEM filename (it is the tif file, that you can also open in QGis)
dem_filename = 'BDAltiv2_75m.tif'
# full path of the dem tif file
dem_path = data_path + dem_filename
# Put load to False so that the watershed is created from scratch
load = False
# Complete the watershed name
watershed_name = 'Glueyre'
# Extract the watershed with the outlet coordinates
from_xyv = [820019.377455, 6.41561849e+06, 75, 10, 'EPSG:2154'] # [x, y, snap distance, buffer size]
# save_object to True will save the watershed object in the out_path for future reutilisation
save_object = True


#%% Plot the area where the catchment is located 

from rasterio.plot import show
from matplotlib_scalebar.scalebar import ScaleBar
dem_tmp = rasterio.open(dem_path)
fig, ax = plt.subplots(1, 1, figsize=(3,3), dpi=300)

bounds = dem_tmp.bounds
xlim = ([bounds[0], bounds[2]])
ylim = ([bounds[1], bounds[3]])
ax.set_xlim(xlim)
ax.set_ylim(ylim)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
ax.set(aspect='equal') 
scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower left')

ax.imshow(np.ma.masked_where(dem_tmp.read(1) < -100,dem_tmp.read(1)), cmap='terrain')
show(np.ma.masked_where(dem_tmp.read(1) < -100, dem_tmp.read(1)), ax=ax, transform=dem_tmp.transform, 
         cmap='terrain', alpha=0.75, zorder=2, aspect="auto")
ax.plot(from_xyv[0],from_xyv[1],'ro')


#%% Select the folder where the data will be stored 

out_path = '/home/jean.marcais/Bureau/tmp/hydromodpy/'
#out_path = 'C:/Users/ronan/Simulations/HydroModPy/'
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'


#%% Launch hydromopy first step

print('##### '+watershed_name.upper()+' #####')
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=None, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=None, # [path, cell size]
                              from_shp=None, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              #bottom_path=bottom_path, # path
                              #modflow_path=modflow_path, 
                              save_object=save_object)


#%% Visualize what happened 

visualization_watershed.watershed_dem(BV)


#%% Add ancillary data

BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['cours_eau_V'], fields_obs=['fid'])
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')


#%%

visualization_watershed.watershed_geology(BV)


#%% 4. Load climatic reanalysis

# ### Load it from preextracted data 

BV.add_climatic()
BV.climatic.update_recharge_reanalysis(path_file=data_path+'_climate_REANALYSIS_mperday.csv',
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2019,
                                       time_step='D',
                                       sim_state='transient')
BV.climatic.update_runoff_reanalysis(path_file=data_path+'_climate_REANALYSIS_mperday.csv',
                                     clim_mod='REA',
                                     clim_sce='historic',
                                     first_year=1990,
                                     last_year=2019,
                                     time_step='D',
                                     sim_state='transient')
BV.climatic.recharge = BV.climatic.recharge.resample('M').mean()
BV.climatic.runoff = BV.climatic.runoff.resample('M').mean()


#%% Alternative : download it from Meteo France

# BV.add_climatic()
# BV.climatic.update_sim2_reanalysis(var_list=['precip','recharge', 'runoff',],
#                                    nc_data_path=data_path,
#                                    first_year=2000,
#                                    last_year=2010,
#                                    time_step='M',
#                                    sim_state='transient',
#                                    spatial_mean=True,
#                                    geographic=BV.geographic,
#                                    disk_clip='watershed')

# ### Units
# BV.climatic.update_recharge(BV.climatic.recharge / 1000, sim_state='transient') # from mm/day to m/day
# BV.climatic.update_runoff(BV.climatic.runoff / 1000, sim_state='transient') # from mm to m/day
# BV.climatic.precip = BV.climatic.precip / 1000 # from mm to m/day


#%% Climatic visualization

fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge.resample('Y').mean()*1000*365
r = BV.climatic.runoff.resample('Y').mean()*1000*365
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('[mm/year]')
ax.legend()


#%% 5. Run your first steady state Model with Hydromodpy

# ### Choose your hydrogeologic parametrization

sim_state = 'steady' # 'steady' or 'transient'
# choose type of aquifer thickness
bottom = None #None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness

# choose aquifer porosity and hydraulic conductivity
porosity = 10 / 100 # -
hyd_cond = 1e-6 * 24 * 3600 # similar unit as the recharge [m/day]

# choose recharge and runoff values 
recharge_values = toolbox.select_period(BV.climatic.recharge, 2000, 2010) # in m/day
runoff_values = toolbox.select_period(BV.climatic.runoff, 2000, 2010) # in m/day


#%% Choose (or let it as default) vertical heterogeneity in the aquifer

nlay = 1
lay_decay = 1 # 1 for no decay
cond_decay = 1 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]],
                  #      [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)


#%% Useful parametrization

box = True # or False
sink_fill = False # or True
plot_cross = False
first_clim = 'mean'
split_temp = True
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL


#%% Define hydromodpy settings

BV.add_settings()
BV.add_geometric() # soon
BV.add_hydraulic()

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

BV.climatic.update_first_clim(first_clim)
BV.settings.update_split_temporal(split_temp) # if True, split each stress-period with perlen in relation to the rehcarge datetime freq (weekly, monthly, yearly)

BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

BV.climatic.update_recharge(recharge_values[:], sim_state=sim_state)
BV.climatic.update_runoff(runoff_values[:], sim_state=sim_state)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_hyd_cond(hyd_cond)


#%% Run your steady state model and export hydromodpy results 

set_simulations = 'parametrization_exploration'
model_name = set_simulations+'_k_'+str(round(hyd_cond,3))+'_porosity_'+str(round(porosity,2))+'_thick_'+str(round(thick))+'_rech_'+str(round(recharge_values.mean()*1000*365))
BV.settings.update_model_name(model_name)
print(model_name)

model_modflow = BV.preprocessing_modflow()
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
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


#%%
success_modflow


#%% 6. Results visualization

visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                             'watertable', 'watertable_depth',
                             #'drain_flow','surface_flow',
                             #'pathlines', 'residence_times'
                             ],
              color_scale = [(None,None),(None,None),
                             (None,None),(0,10),
                             #(None,None),(None,None),
                             #(None,None),(None,None),
                             ], 
              lines=100)


#%%

dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif') # dem data
stream_data = imageio.imread(stable_folder+'/hydrography/'+'cours_eau_V.tif') # river data
watertable_data = imageio.imread(simulations_folder+'/'+model_name+'/_postprocess/_rasters/'+'watertable_elevation_t(0).tif') # watertable data
interactive = True # problem of visuqlization windows, to large in a little PC screen
visu = visualization_results.Visualization(BV, model_name)
visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)


#%%

fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

wt_data = imageio.imread(os.path.join(simulations_folder, model_name, 
                                      r'_postprocess/_rasters/watertable_elevation_t(0).tif'))
wt_data = np.ma.masked_where(wt_data < 0, wt_data)

river_data = imageio.imread(os.path.join(stable_folder, 'hydrography', 
                                         'cours_eau_V.tif'))

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
if bottom==None:
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                            dem_v_plot-thick, wt_v_plot,
                            color='dodgerblue', alpha=0.5, lw=0)
else:
    dem_b_plot = dem_v_plot.astype(float)
    dem_b_plot[dem_b_plot>0] = bottom
    wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75,
                            dem_b_plot, wt_v_plot,
                            color='dodgerblue', alpha=0.5, lw=0)
# Line watertable
w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1)

# Facecolor unsaturated
wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, 
                            wt_v_plot, dem_v_plot,
                            color='saddlebrown', alpha=0.5, lw=0)

# Line unsaturated
d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)

if bottom==None:
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_v_plot-thick,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-thick, color='dimgray', lw=1.5)
else:
    # Facecolor noflow
    ax.fill_between(np.arange(xx.shape[0])*75,
                    0, dem_b_plot,
                    color='lightgrey', alpha=1, lw=0, zorder=10)
    # Line noflow
    ax.plot(np.arange(xx.shape[0])*75, dem_b_plot, color='dimgray', lw=1.5)

# Settings
ax.set_xlim(6500, 8000)
ax.set_ylim(500, 1100)
# ax.set_yticks([90,100,110,120,130])
ax.set_xlabel('Distance [m]')
ax.set_ylabel('Elevation [m]')
ax.set_title('K = '+'{:.2e}'.format(model_modflow.hyd_cond.mean()/24/3600)+' m/s')


fig.tight_layout


#%%


fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

contour = imageio.imread(BV.geographic.watershed_contour_tif)
contour = np.ma.masked_where(contour < 0, contour)

obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                             'cours_eau_V.tif'))
obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)

seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                              r'_postprocess/_rasters/seepage_areas_t(0).tif'))
seep_river_data = np.ma.masked_where(seep_river_data <= 0, seep_river_data)

sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                             r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
sim_river_data = np.ma.masked_where(sim_river_data <= 0, sim_river_data)

im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
# im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7)
im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.5)

ax.set_xlabel('X [pixels]')
ax.set_ylabel('Y [pixels]')
ax.set_title('K = '+'{:.2e}'.format(model_modflow.hyd_cond.mean()/24/3600)+' m/s')
fig.tight_layout()


#%% 7. Transient MODFLOW model

# ### Reload climatic reanalysis

BV.add_climatic()
BV.climatic.update_recharge_reanalysis(path_file=data_path+'_climate_REANALYSIS_mperday.csv',
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2019,
                                       time_step='D',
                                       sim_state='transient')
BV.climatic.update_runoff_reanalysis(path_file=data_path+'_climate_REANALYSIS_mperday.csv',
                                     clim_mod='REA',
                                     clim_sce='historic',
                                     first_year=1990,
                                     last_year=2019,
                                     time_step='D',
                                     sim_state='transient')
BV.climatic.recharge = BV.climatic.recharge.resample('M').mean()
BV.climatic.runoff = BV.climatic.runoff.resample('M').mean()


#%% Set transient option for sim_state and choose parametrization

sim_state = 'transient' # 'steady' or 'transient'
# choose type of aquifer thickness
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 50 # if bottom is None, aquifer thickness

# choose aquifer porosity and hydraulic conductivity
porosity = 10 / 100 # -
hyd_cond = 1e-4 * 24 * 3600 # similar unit as the recharge [m/day]

# choose recharge and runoff values 
starting_year = 2000
ending_year = 2005
recharge_values = toolbox.select_period(BV.climatic.recharge, starting_year, ending_year) # in m/day
runoff_values = toolbox.select_period(BV.climatic.runoff, starting_year, ending_year) # in m/day


#%% Define hydromodpy settings

BV.add_settings()
BV.add_geometric() # soon
BV.add_hydraulic()

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

BV.climatic.update_first_clim(first_clim)
BV.settings.update_split_temporal(split_temp) # if True, split each stress-period with perlen in relation to the rehcarge datetime freq (weekly, monthly, yearly)

BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

BV.climatic.update_recharge(recharge_values[:], sim_state=sim_state)
BV.climatic.update_runoff(runoff_values[:], sim_state=sim_state)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_hyd_cond(hyd_cond)


#%% Run your transient model and export hydromodpy results 

set_simulations = 'transient_simulation'
model_name = set_simulations+'_k_'+str(round(hyd_cond,3))+'_porosity_'+str(round(porosity,2))+'_thick_'+str(round(thick))+'_rech_'+str(round(recharge_values.mean()*1000*365))
BV.settings.update_model_name(model_name)
print(model_name)

model_modflow = BV.preprocessing_modflow()
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
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


#%% Export time series of the simulation


if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = True,
                              persistency_index=True,
                              export_all_tif = False)

    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=None,
                                                      actual_date=True, 
                                                      subbasin_results=True) # or None


#%% Import measured hydrometry


Q_mes_df = pd.read_csv(data_path+'V4145210_QmM.csv', sep=',')
Q_mes_df['Date (TU)'] = pd.to_datetime(Q_mes_df['Date (TU)'], format='%Y-%m-%dT%H:%M:%S.000Z') 
Q_mes_df.index = Q_mes_df['Date (TU)']


#%% Retain only data corresponding to the modeled period


Q_mes_df = toolbox.select_period(Q_mes_df, starting_year, ending_year) # in m/day


#%% Plot

import pandas as pd 
from matplotlib import pyplot as plt
timeseries_df = pd.read_csv(timeseries_results.timeseries_file+'/_simulated_timeseries.csv', sep=';')
timeseries_df.date = pd.to_datetime(timeseries_df.date)
plt.plot(timeseries_df.date,(timeseries_df.outflow_drain+timeseries_df.runoff)*BV.geographic.area*1e6/86400)
plt.plot(Q_mes_df.index,Q_mes_df['Valeur (en l/s)']/1000)





