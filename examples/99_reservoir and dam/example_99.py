# -*- coding: utf-8 -*-
"""
Created on Wed Dec  6 22:19:57 2023

@author: coche
"""


#%% ---- LIBRAIRIES

#%% PYTHON

# Libraries installed by default
import sys
import os
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

# Libraries added from 'conda install' procedure
import matplotlib as mpl        # install automatically by geopandas
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable

# # Libraries added from 'pip install' procedure
import deepdish as dd
import imageio
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
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL
data_path = os.path.join(os.path.split(os.path.split(root_dir)[0])[0], r"1- Veille", r"4- Donnees")
# =============================================================================
# example_path = root_dir + "/examples/99_reservoir and dam/"
# data_path = example_path + "data/"
# =============================================================================
# out_path = os.path.join(folder_root.root_folder_results(), 'cheze_0.1')
out_path = folder_root.root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()

#%% ---- WATERSHED

#%% OPTIONS
dem_path = os.path.join(data_path, 
                        r"0- MNT\IGN\MNT_fusion", 
                        "MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif")
load = False
watershed_name = 'cheze_Dam_3.8'
# outlet after the dam ("pont romain")
from_xyv = [331315, 6781273, 200, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
# Station de débit à Plélan-le-Grand : [x, y] = [324472, 6779605]
save_object = True

#%% GEOGRAPHIC
print('##### '+watershed_name.upper()+' #####')

BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load, # load = False
                              watershed_name=watershed_name,
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              save_object=save_object)

#%%% Reload
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              watershed_name=watershed_name,
                              load=True)

#%%% Paths
# Paths generated automatically but necessary for plots
stable_folder = BV.geographic.stable_folder
simulations_folder = BV.geographic.simulations_folder
# Or:
# =============================================================================
# stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
# simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
# =============================================================================

#%% DATA
# Clip specific data at the catchment scale
geol_path = os.path.join(data_path,
                         r"14- Geologie\GEO1M")
BV.add_geology(geol_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')

hydrography_path = os.path.join(data_path,
                                r"5- Rivieres\BD Topage CoursEau_FXX-shp")
BV.add_hydrography(hydrography_path, types_obs=['CoursEau_FXX'], fields_obs=['fid'])

hydrometry_path = os.path.join(data_path,
                               r"10- Stations et debits\Stations jaugeage\HydroModPy")
BV.add_hydrometry(hydrometry_path, 'france hydrometric stations.shp')

intermittency_path= os.path.join(data_path,
                                 r"10- Stations et debits\ONDE")
BV.add_intermittency(intermittency_path, 'regional onde stations.shp')

BV.add_piezometry()

# =============================================================================
# BV.add_lakeres(stable_folder)
# =============================================================================

# Extract some subbasin from data available above
# =============================================================================
# BV.add_subbasin(os.path.join(data_path,"additional"), 200)
# =============================================================================
BV.add_subbasin(os.path.join(root_dir, 'examples', 
                             '99_reservoir and dam', 'data', 'additional'), 200)
# Normalement pas besoin car c'est déjà un point d'intérêt

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% RECHARGE and RUNOFF (Input data)
BV.add_climatic()
sim_state = 'transient'

#%%% Safran Surfex
BV.add_safransurfex(clip_path)

#%%% Reanalyse
rea_path = os.path.join(data_path,
                        r"8- Meteo\Surfex",
                        "_climate_REANALYSIS.csv")
BV.climatic.update_recharge_reanalysis(path_file=rea_path,
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=1990,
                                       last_year=2021,
                                       time_step='D',
                                       sim_state='transient')
BV.climatic.recharge = BV.climatic.recharge / 1000 # from mm to m

BV.climatic.update_runoff_reanalysis(path_file=rea_path,
                                     clim_mod='REA',
                                     clim_sce='historic',
                                     first_year=1990,
                                     last_year=2021,
                                     time_step='D',
                                     sim_state='transient')
BV.climatic.runoff = BV.climatic.runoff / 1000 # from mm to m

### Select time period
recharge = BV.climatic.recharge
BV.climatic.update_recharge(recharge['2004-01-01':'2004-03-01'],
                            sim_state = sim_state)
# =============================================================================
# BV.climatic.update_recharge(recharge['2004-01-01':'2020-01-01'],
#                             sim_state = sim_state)
# =============================================================================
# =============================================================================
# BV.climatic.update_recharge(recharge['2010-07-01':'2014-12-31'],
#                             sim_state = sim_state)
# =============================================================================
runoff = BV.climatic.runoff 
BV.climatic.update_runoff(runoff['2004-01-01':'2004-03-01'],
                          sim_state = sim_state)
# =============================================================================
# BV.climatic.update_runoff(runoff['2004-01-01':'2020-01-01'],
#                           sim_state = sim_state)
# =============================================================================
# =============================================================================
# BV.climatic.update_runoff(runoff['2010-07-01':'2014-12-31'],
#                           sim_state = sim_state)
# =============================================================================

### Figures of chronics
# Yearly (matplotlib)
fig, ax = plt.subplots(1,1, figsize=(6,3))
# =============================================================================
# R = BV.climatic.recharge.resample('Y').sum()*1000 # [m] -> [mm]
# r = BV.climatic.runoff.resample('Y').sum()*1000 # [m] -> [mm]
# =============================================================================
R = recharge.resample('Y').sum()*1000 # [m] -> [mm]
r = runoff.resample('Y').sum()*1000 # [m] -> [mm]
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=1)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=1)
ax.set_xlabel('Time')
ax.set_ylabel('[mm/year]')
ax.legend()

# Daily (matplotlib)
fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge*1000 # [m] -> [mm]
r = BV.climatic.runoff*1000 # [m] -> [mm]
# =============================================================================
# R = recharge*1000 # [m] -> [mm]
# r = runoff*1000 # [m] -> [mm]
# =============================================================================
ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=1)
ax.plot(r, label='runoff_reanalysis', c='navy', lw=1)
ax.set_xlabel('Time')
ax.set_ylabel('[mm/day]')
ax.legend()

#%%% Explore 1
BV.climatic.update_recharge_explore1(path_file=data_path+'_climate_EXPLORE1.csv',
                                     clim_mod='IPS1',
                                     clim_sce='RCP8.5',
                                     first_year=2020,
                                     last_year=2099,
                                     time_step='D',
                                     sim_state='transient')
BV.climatic.update_runoff_explore1(path_file=data_path+'_climate_EXPLORE1.csv',
                                     clim_mod='IPS1',
                                     clim_sce='RCP8.5',
                                     first_year=2020,
                                     last_year=2099,
                                     time_step='D',
                                     sim_state='transient')
fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge.resample('Y').sum()*1000
r = BV.climatic.runoff.resample('Y').sum()*1000
ax.plot(R, label='recharge_explore1', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_explore1', c='navy', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('[mm/year]')
ax.legend()

#%%% Explore 2
BV.climatic.update_recharge_explore2(path_file=data_path+'_climate_EXPLORE2.csv',
                                     gcm_mod='CNR',
                                     rcm_mod='ALA',
                                     sce_mod='RCP8.5',
                                     first_year=2020,
                                     last_year=2099,
                                     sim_state='transient')
BV.climatic.update_runoff_explore2(path_file=data_path+'_climate_EXPLORE2.csv',
                                     gcm_mod='CNR',
                                     rcm_mod='ALA',
                                     sce_mod='RCP8.5',
                                     first_year=2020,
                                     last_year=2099,
                                     sim_state='transient')
fig, ax = plt.subplots(1,1, figsize=(6,3))
R = BV.climatic.recharge.resample('Y').sum()*1000
r = BV.climatic.runoff.resample('Y').sum()*1000
ax.plot(R, label='recharge_explore2', c='dodgerblue', lw=2)
ax.plot(r, label='runoff_explore2', c='navy', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('[mm/year]')
ax.legend()

#%% DAM
# In this version, the lake is defined in a new modflow layer added on top of the modeL

BV.add_lakeres(BV.stable_folder)

######################
### --- lake 1 --- ###
######################
# Add new lake/reservoir
# ----------------------
lake_id = 'reservoir_cheze'
maskmx_path = os.path.join(root_dir, 'examples', 
                             '99_reservoir and dam', 'data', 
                             'Cheze_lake_75m_outside.tif')
# =============================================================================
# maskmx_path = os.path.join(root_dir, 'examples', 
#                              '99_reservoir and dam', 'data', 
#                              'Cheze_polygon_englob.shp')
# =============================================================================
BV.lakeres.new_lakeres(maskmx_path, lake_id)

# Geometry and physical properties
# --------------------------------
BV.lakeres.update_stageinit(lake_id, 70) # [m]
BV.lakeres.update_stagemax(lake_id, 90) # [m]
# BV.lakeres.update_volumemax(lake_id, 14e6) # [m3]
BV.lakeres.update_lakebed_leakance(lake_id, 1e-6 * 24 * 3600) # bedlake leakance [m/day]
                                                              # here equiv. to 1e-6 m/s
bathymetry_raster = os.path.join(root_dir, 'examples', 
                             '99_reservoir and dam', 'data',
                             'Cheze_bathy_1m_NGF-elevation_v2enlarged.nc')
                             # 'bathymetry_25m_NGF-elevation.tif')
BV.lakeres.update_bathymetry(lake_id, bathymetry_raster)
# =============================================================================
# BV.lakeres.update_bathymetry(lake_id, bathymetry_raster, mode = 'elevation')
# # mode can be 'elevation', 'depth', 'height' (= -depth)
# =============================================================================

# Input fluxes
# ------------
dam_data_path = os.path.join(os.path.split(data_path)[0], 
                             r"1- Biblio locale\14- Barrage",
                             "Documents_travail_Ronan\dam_data",
                             r"dam_cheze_volume_raw_2000-2022.csv")

dam_input_df = pd.read_csv(dam_data_path,
                           sep = ";",
                           header = 0,
                           skiprows = 0,
                           index_col = 'time',
                           parse_dates = True)

# Convert values (monthly sums) into daily rates 
days_in_month = pd.DataFrame( 
    index = dam_input_df.index,
    data = dam_input_df.index.days_in_month)
days_in_month.rename(columns = {'time':'n_days'}, inplace = True)
dam_input_df = dam_input_df.divide(days_in_month.n_days, axis="index")

# Environmental fluxes (by default, fluxes are set to 0) 
# User can update these fluxes with float, file path, or "from_climatic" mode
BV.lakeres.update_precip(lake_id, dam_input_df['ppt_surf']/1.73e6) # because Ronan's values were summed over 1.73 km² area
# BV.lakeres.update_evap(lake_id, 'from_climatic')
BV.lakeres.update_evap(lake_id, dam_input_df['ae_oudin']/1.73e6)
BV.lakeres.update_runoff(lake_id, BV.climatic.runoff * (30-3.31)*1e6) # because runoff has to be a volume (summed over the area runing off towards the lake)

# Anthropic fluxes
withdraw_fill_ts = dam_input_df['usine'] - dam_input_df['canut'] - dam_input_df['meu'] 
# For now we can add here the upstream flow and substract the return flux
withdraw_fill_ts = withdraw_fill_ts + dam_input_df['resti'] - 3*dam_input_df['stream'] # the x3 factor is added to account for lateral streams
BV.lakeres.update_withdraw_fill(lake_id, withdraw_fill_ts)
# if values are daily rates, then user should indicate daily = True

# Otherwise, the Cheze river discharge (en amont) can be found here:
    # D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\10- Stations et debits\Debits\J736422001_QmnJ(n=1_non-glissant) raw_cheze_plelan-le-grand.csv

# =============================================================================
# ########################
# ### --- lake 412 --- ###
# ########################
# lake_id = 412
# dummy_maskmx_path = os.path.join(root_dir, 'examples', 
#                              '99_reservoir and dam', 'data', 
#                              'Dummy_lake.shp')
# BV.lakeres.new_lakeres(dummy_maskmx_path, lake_id)
# =============================================================================


######################
### --- others --- ###
######################
# =============================================================================
# BV.lakeres.update_definition(lake_id, new_lake_id, new_mask_path)
# =============================================================================

# =============================================================================
# BV.lakeres.remove(lake_id)
# =============================================================================


BV.save_object()

#%%% Force the return flow
# Return flow time series
return_flow_series = dam_input_df['resti']
# return_flow_series can also be a .txt file

# Coordinates of the cell where the return flow is mesured
return_flow_coords = (331500, 6781425) # tuple or list of tuples 
# =============================================================================
# fixed_flow_coords = os.path.join(root_dir, 'examples', '99_reservoir and dam',
#                                  'data', 'additional', 'coords_forcedflow.txt')
# =============================================================================
                    # the coords can also be indicated as a .txt file

bound_id = 0 # identifier for the cell (or cells) where the return flow will be forced
snap_dist = 200
BV.settings.add_flowbound(bound_id, return_flow_coords, snap_dist,
                          return_flow_series)

# To remove a forced-flow cell or group of cells:
# BV.lakeres.remove_flowbound(bound_id)

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
box = True # or False
sink_fill = False # or True
plot_cross = True

# Climatic settings
first_clim = 'mean' # or 'first or value

# Hydraulic settings
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
hyd_cond = 3.4e-5 * 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 0.1 / 100 # [%]
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Boundary settings
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL

# Particle tracking settings
zone_partic = 'watershed' # or 'domain''

#%% UPDATE

# Import modules
BV.add_settings()

# Model name
model_name = 'base'
BV.settings.update_model_name(model_name)

# BV.add_climatic()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Climatic settings
# BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_first_clim(first_clim)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)
BV.add_oceanic(sea_level)

# Particle tracking settings
BV.settings.update_input_particules(zone_partic=zone_partic)

# Lakes/reservoir
try:
    BV.lakeres
except AttributeError:
    BV.lakeres = None

BV.save_object()


#%% ---- MODELING

#%% MODFLOW

# model_modflow = BV.preprocessing_modflow(BV.simulations_folder)
model_modflow = BV.preprocessing_modflow()
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

h5file = os.path.join(simulations_folder,
                      'results_listing_' + model_name)

#%%% Save
mdflw_dict = {}
mdflw_dict['model_name'] = model_name
mdflw_dict['success_modflow'] = success_modflow
mdflw_dict['model_modflow'] = model_modflow

dd.io.save(h5file, mdflw_dict)

#%%% Reload
model_name = 'base'

h5file = os.path.join(simulations_folder,
                      'results_listing_' + model_name)

mdflw_dict = dd.io.load(h5file)
model_name = mdflw_dict['model_name']
success_modflow = mdflw_dict['success_modflow']
model_modflow = mdflw_dict['model_modflow']

#%%% Post-processing
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True, 
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = True,
                              lake_seepage = True,
                              export_all_tif = False,
                              export_netcdf = True,)

#%% MODPATH (only in steady state)
if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particules_shp=True,
                                  random_id=100)
        
#%% TIMESERIES
model_modpath = None # because transient

timeseries_results = BV.postprocessing_timeseries(geographic=BV.geographic,
                                                  lakeres=BV.lakeres,
                                                  model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True) # or None

#%% ---- PLOT

#%% CROSS
fig, ax = plt.subplots(1, 1, figsize=(5,3), dpi=300)

stable_folder = os.path.join(out_path,
                             watershed_name,
                             'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path,
                                  watershed_name,
                                  'results_simulations')

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data = np.ma.masked_where(dem_data < 0, dem_data)

wt_data = imageio.imread(os.path.join(model_modflow.tifs_file,
                                      'watertable_elevation_t(0).tif'))
wt_data = np.ma.masked_where(wt_data < 0, wt_data)

river_data = imageio.imread(os.path.join(stable_folder,
                                         'hydrography',
                                         'CoursEau_FXX.tif'))

xvalues = np.linspace(-1,1,dem_data.shape[1])
yvalues = np.linspace(-1,1,dem_data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues) # Return a list of coordinate matrices from coordinate vectors.

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

fig.tight_layout

fig.savefig(os.path.join(model_modflow.figure_file,
                         '_'.join(['CROSS', model_name, 
                                   'watertable_elevation', 't=0']) + '.png'),
            bbox_inches='tight')
    
fig.savefig(os.path.join(model_modflow.save_fig,
                         '_'.join(['CROSS', model_name,
                                   'watertable_elevation', 't=0']) + '.png'),
            bbox_inches='tight')