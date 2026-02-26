# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% ---- LIBRAIRIES

#%% PYTHON

# Libraries installed by default
import sys
import os

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import xarray as xr
import rioxarray as rxr
import pickle
import flopy

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

import glob

#%% ROOT

"""
# Import HydroModPy modules
from os.path import dirname, abspath
# DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
DIR = 'C:/Users/rabherve/GitHub/HydroModPy-dev/'
sys.path.append(DIR)
"""

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
sys.path.append(os.path.join(DIR, "hydromodpy"))

# from os.path import dirname, abspath
# root_dir = dirname(dirname(dirname(abspath(__file__))))
# sys.path.append(root_dir)

#%% HYDROMODPY

import hydromodpy
import importlib

# Import HydroModPy modules
from hydromodpy import watershed_root
from hydromodpy.watershed import climatic, geographic, geology, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from hydromodpy.modeling import downslope, modflow, modpath, timeseries
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

from hydromodpy.modeling import downslope, modflow, modpath, timeseries
from hydromodpy.pyhelp.pyhelp_netcdf import preprocessing_pyhelp

#%% PERSONAL

data_path = 'C:/Users/mathi/dev2/HydroModPy/users/pelissier/10_intermittency/data/'

# The folder out_path is created in the example_path root directory:
out_path = 'C:/Users/mathi/Downloads/results_intermittency/'

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

# cell_size = 100
# wbt.resample(os.path.join(data_path, "ursa_RS3_rot0.tif"),
#              os.path.join(data_path, "ursa_RS3_rot0_"+str(cell_size)+".tif"),
#              cell_size)
# dem_path = os.path.join(data_path, "ursa_RS3_rot0_"+str(cell_size)+".tif")

dem_path_pyhelp = os.path.join(data_path, "ursa_RS3_rot0_250.tif")
# dem_path = os.path.join(data_path, "ursa_RS3_rot0.tif")
dem_path = os.path.join(data_path, "poschiavo.tif")

watershed_name = "Example_10_Urse"
# watershed_name ='Strengbach'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = [os.path.join(data_path, "watershed_urse_EPSG2056.shp"), 10]
# from_xyv = [327816.965, 6777886.670, 150, 20 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
from_xyv = [2798418.619, 1133789.585, 500, 20, 'EPSG:2056']
bottom_path = None # path
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

# load = True
load = False
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=load,
                              watershed_name=watershed_name,
                              from_lib=from_lib, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=from_dem, # [path, cell size]
                              from_shp=from_shp, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=bottom_path, # path 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

#%% DATA

KB4_loc = [2796960.102,1133328.361] #???
visualization_watershed.watershed_dem(BV)

# BV.add_hydrography()

#%% ---- PYHELP

#%% PATH

pyhelp_workdir = os.path.join(out_path, watershed_name, "results_pyhelp")
era5_folder = os.path.join(data_path)

### If already completed grid: 
grid_base_csv = data_path+"/"+"_init_input_grid_base1/"+"input_grid_base1.csv"

ready_csvs = [
    os.path.join(era5_folder, "precip_input_data.csv"),
    os.path.join(era5_folder, "airtemp_input_data.csv"),
    os.path.join(era5_folder, "solrad_input_data.csv")
]

#%% RUN

# k_values = [4.28e-8 * 3600 * 24] #◘ 0.0037 m/day

# list_of_sims = []

# option = '1'

# for k in k_values[:]:
    
#     k = round(k, 5)
    
#     grid_kwargs = dict(
#                        growth_start=140,
#                        growth_end=280,
#                        wind=2.5,
#                        hum1=60, hum2=65, hum3=70, hum4=70,
#                        LAI=2.4, 
#                        EZD=44.5,
#                        CN=55,
#                        nlayer=1,  
#                        lay_type1=1,
#                        thick1=100,
#                        poro1=0.45,
#                        fc1=0.23,
#                        wp1=0.116,
#                        ksat1=k,
#                        dist_dr1=50,
#                        slope1=35
#                        )
    
#     # cid                             Unique cell ID
#     # lat_dd                          Decimal degrees Latitude of the cell centroid
#     # lon_dd                          Decimal degrees Longitude of the cell centroid
    
#     # wind            km/h            Average annual wind speed
#     # hum1            %               Average quarterly relative humidity (Jan to Mar)
#     # hum2            %               Average quarterly relative humidity (Apr to Jun)
#     # hum3            %               Average quarterly relative humidity (Jul to Sep)
#     # hum4            %               Average quarterly relative humidity (Oct to Dec)
#     # growth_start    julian day      First day of the growing season
#     # growth_end      julian day      Last day of the growing season
#     # LAI             –               Maximum leaf area index
#     # EZD             cm              Evaporative zone depth
#     # CN              –               Curve Number
#     # nlayer          –               Number of hydrostratigraphic layers at cell cid
#     # lay_type{i}     –               Type of HELP layer of the ith soil layer
#     # thick{i}        cm              Thickness of the ith soil layer
#     # poro{i}         m3/m3           Total porosity of the ith soil layer
#     # fc{i}           m3/m3           Field capacity of the ith soil layer
#     # wp{i}           m3/m3           Wilting point of the ith soil layer
#     # ksat            cm/s            Saturated hydraulic conductivity of the ith soil layer
#     # dist_dr         m               Distance to discharge
#     # slope           %               Average slope
    
#     # run             –               Identify cells to be run with the HELP model
#     # context         –               Identify cells by context:
#     #     0 - Water cell
#     #     1 - Normal cell
#     #     2 - Stream edge with superficial hypodermic runoff
#     #     3 - River edge with deep hypodermic runoff
#     #     4 - Urban cell
#     #     5 - Cell not mapped
    
#     if option == '1':
    
#         #---- Input climatic ready - Input grid updated:
#         nc = preprocessing_pyhelp(
#             workdir = os.path.join(pyhelp_workdir, f"_sim_{k}"),
#             outpath = os.path.join(pyhelp_workdir, f"_sim_{k}"),
#             ready_csvs = ready_csvs,
#             grid_kwargs = grid_kwargs,
#             dem = dem_path_pyhelp,
#             shapefile = from_shp[0],
#         )
#         # print("NetCDF :", nc)
    
#     if option == '2':
    
#         #---- Input climatic ready - Input grid ready:
        
#         nc = preprocessing_pyhelp(
#             workdir = pyhelp_workdir,
#             outpath = simulations_folder,
#             grid_csv = grid_base_csv,
#             ready_csvs = ready_csvs,
#         )
#         # print("NetCDF :", nc)

#     """
#     if option == '3':
    
#         #---- Input climatic updated - Input grid updated:
#         nc = preprocessing_pyhelp(
#             workdir = pyhelp_workdir,
#             outpath = simulations_folder,
#             dem = dem_path_pyhelp,
#             era5_folder = era5_folder,
#             grid_kwargs = grid_kwargs,           
#             conda_env   = "pyhelp_env",
#         )
#         # print("NetCDF :", nc)
#     """
    
#     list_of_sims.append(f"_sim_{k}")

#%% FORMATING

name_sim = "_sim_0.0037"

csv_path = pyhelp_workdir + '/' + name_sim + "/help_example_daily_mean.csv"

df = pd.read_csv(csv_path)
df = df.rename(columns={df.columns[0]: "time"})
formatted_csv_path =  pyhelp_workdir + '/' + name_sim + "/help_example_daily_mean_formatted.csv"
df.to_csv(formatted_csv_path, index=False)

#%% SCALING

nc_path  = pyhelp_workdir + '/' + name_sim + "/_pyhelp_outputs_grid.nc"
dem_path = stable_folder + "/geographic/watershed_box_buff_dem.tif"

ds  = xr.open_dataset(nc_path)
dem = rxr.open_rasterio(dem_path)

R = ds["rechg"]  
R = R.rio.write_crs(dem.rio.crs)

Rt   = R.rio.reproject_match(dem, nodata=0.0)
cube = Rt.values / 1000

recharge_dict = {i: cube[i] for i in range(cube.shape[0])}

#%% YEARLY

rec_path = pyhelp_workdir + '/' + name_sim + "/help_example_daily_mean_formatted.csv"

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])
# rec_mean[rec_mean==0] = np.nan
years = rec_mean.index.year.unique()

# Calculer la moyenne annuelle
rec_annual = rec_mean.resample('Y').sum()

# Extraire les années pour l'axe X
years = rec_annual.index.year
rec_annual.index = years  # Remplacer l'index par les années pures

# Tracé
plt.figure(figsize=(9, 4), dpi=150)

plt.plot(rec_annual.index, rec_annual['rechg'], color='blue', lw=5)

plt.xlabel('Years')
# plt.yscale('log')  # Optionnel selon échelle
plt.grid(True, which='both', linestyle='--', alpha=0.5)
plt.title('Yearly recharge [mm/year]')

# Mettre les années en xticks proprement
plt.xticks(ticks=years, labels=[str(y) for y in years])

plt.tight_layout()
plt.show()

#%% MONTHLY

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
# rec_mean = rec_mean.set_index(['time'])
# rec_mean[rec_mean==0] = np.nan
years = rec_mean['time'].dt.year.unique()

# Ajouter colonnes année et mois
rec_mean['year'] = rec_mean['time'].dt.year
rec_mean['month'] = rec_mean['time'].dt.month

# Sélectionner uniquement les colonnes numériques à sommer
cols_to_sum = ['rechg']

# Grouper par année et mois, et sommer
rec_monthly = rec_mean.groupby(['year', 'month'], as_index=False)[cols_to_sum].sum()

# Créer une colonne datetime pour l'axe x (1er jour de chaque mois)
rec_monthly['time'] = pd.to_datetime(dict(year=rec_monthly['year'], month=rec_monthly['month'], day=1))

# Mettre en index temporel
rec_monthly = rec_monthly.set_index('time')

# Liste des années
years = rec_monthly['year'].unique()

# Tracé
fig, axs = plt.subplots(3, 1, figsize=(8, 10), dpi=300, sharey=True)
axs = axs.ravel()

for i, y in enumerate(years[:]):  # Saute la première année si besoin
    ax = axs[i]
    data_y = rec_monthly[rec_monthly['year'] == y]

    ax.plot(data_y.index, data_y['rechg'], color='blue', lw=4, zorder=2)

    ax.set_yscale('log')
    ax.set_xlim(pd.to_datetime(f'{y}-01-01'), pd.to_datetime(f'{y}-12-31'))
    ax.set_ylim(1e-2, 1e3)
    ax.set_title(str(y))

    month_ticks = pd.date_range(start=f'{y}-01-01', end=f'{y}-12-31', freq='MS')
    ax.set_xticks(month_ticks)
    ax.set_xticklabels([str(m.month) for m in month_ticks])
    
    if i == 0:
        ax.legend(loc='upper left', frameon=False, fontsize=13)

plt.suptitle('Monthly recharge [mm/month]', fontsize=16, y=1)
plt.tight_layout()

#%% DAILY

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])
years = rec_mean.index.year.unique()

fig, axs = plt.subplots(3, 1, figsize=(12, 12), dpi=300, sharey=True)
axs = axs.ravel()

for i, y in enumerate(years[:]):
    ax = axs[i]
    ax.plot(rec_mean['rechg'], color='b', lw=4, zorder=2, label='Ref')
    ax.set_yscale('log')
    ax.set_xlim(pd.to_datetime(f'{y}-01-01'), pd.to_datetime(f'{y}-12-31'))
    ax.set_ylim(1e-2,100)
    ax.set_title(str(y))
    month_ticks = pd.date_range(start=f'{y}-01-01', end=f'{y}-12-31', freq='MS')
    ax.set_xticks(month_ticks)
    ax.set_xticklabels([str(m.month) for m in month_ticks])

plt.suptitle('Daily recharge [mm/day]', y=1)
plt.tight_layout()

#%% ---- DICHOTOMY FOR BEST : K AND ALPHA

#%% DICHOTOMY - FUNCTION

class MatchingStreams:
    """ 
    
    Class for the calibration based on river occurency
        
    Attributes
    ----------
    
    Methods
    ----------
    
    """

    def __init__(self, 
                 watershed, 
                 iteration_label=None):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        self.calibration_folder = watershed.calibration_folder
        self.iteration_label = iteration_label
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        # self.get_indicator()
        
    def prepare_files(self):
        #files are necessary for whiteboxtool
        self.results_folder=os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
        toolbox.create_folder(self.results_folder)
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
        toolbox.create_folder(self.dichotomy_folder)
        
        # Observed buff data
        self.buff_tif_obs = self.hydrography.tif_streams
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        
        # Mask simulated
        tif_sim = os.path.join(self.results_folder,'_rasters','seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
        
    def sim_to_obs(self):
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)   
        
        # Distance of dem to obs
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        
        # Distance of dem to obsflow
        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)

        # Sim to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
        # Simflow to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        # Simflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)
        
        # Distance of dem to sim
        self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
        # Distance of dem to simflow
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)

        # Obs to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        wbt.add_point_coordinates_to_table(self.pt_obsf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
        # Obsflow to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)

#%% DICHOTOMY - RUN

from datetime import datetime

def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

vers = 'aniso11'
types_obs = ['stream_network_urse_reproj']
fields_obs = ['fid']
hydrography_path = data_path  # add hydrographic shapefiles

rec_resamp_month = rec_mean.resample("ME").mean()

recharge = select_period(rec_resamp_month, 2023, 2023) / 1000 # m/day

box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.25 # 1 for no decay
thick = 30 # if bottom is None, aquifer thickness
#print((recharge).mean()*365*1000)
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
sy = 5 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
            
for type_obs, field_obs in zip(types_obs[:], fields_obs[:]):
   
    print('##### '+watershed_name.upper()+' #####')
    
    df = pd.DataFrame()
    
    BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
    area = BV.geographic.area

    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
    BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
    toolbox.create_folder(BV.calibration_folder)
    
    # if not os.path.exists(stable_folder + 'hydrography/' + type_obs + '.tif'):
    BV.add_hydrography(hydrography_path, types_obs=[type_obs], fields_obs=[field_obs])
    # else:
    #     BV.hydrography.streams = stable_folder + 'hydrography/' + type_obs + '.shp'
    #     BV.hydrography.tif_streams = stable_folder + 'hydrography/' + type_obs + '.tif'
            
    BV.add_settings()
    BV.add_climatic()
    BV.add_hydraulic()
    
    BV.settings.update_box_model(box)
    BV.settings.update_sink_fill(sink_fill)
    BV.settings.update_simulation_state(sim_state)
    BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
    BV.climatic.update_recharge(recharge, sim_state=sim_state)
    BV.climatic.update_first_clim(first_clim)
    BV.hydraulic.update_nlay(nlay) # 1
    BV.hydraulic.update_lay_decay(lay_decay) # 1
    BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

    BV.hydraulic.update_cond_drain(cond_drain)
    BV.hydraulic.update_sy(sy)
    BV.hydraulic.update_sy_decay(sy_decay)
    BV.hydraulic.update_ss(ss)
    BV.hydraulic.update_ss_decay(ss_decay)
    BV.hydraulic.update_vka(vka)

    BV.hydraulic.update_hk_vertical(verti_hk)
    BV.hydraulic.update_sy_vertical(verti_sy)
    BV.hydraulic.update_ss_vertical(verti_ss)
    
    BV.add_oceanic(sea_level)
    BV.settings.update_dis_perlen(dis_perlen)
    BV.settings.update_bc_sides(bc_left, bc_right)
    BV.settings.update_input_particles(zone_partic=zone_partic)

    # Aquifer bottom
    list_bottom = [1000] * 9 # aquifer flat or not
    # Decay of K
    list_d_values = [0, 300, 200, 100, 50, 40, 30, 20, 10]
    list_cond_decay = list(1/np.array(list_d_values))      
    list_cond_decay[0] = 0
    list_id_mod = [1,2,3,4,5,6,7,8,9]
    
    # # Aquifer bottom
    # list_bottom = [1000] * 3 # aquifer flat or not
    # # Decay of K
    # list_d_values = [0, 300, 30]
    # list_cond_decay = list(1/np.array(list_d_values))      
    # list_cond_decay[0] = 0
    # list_id_mod = [1,2,3]
    
    # for hk_decay, bottom, id_mod in zip(list_cond_decay[12:13], list_bottom[12:13], list_id_mod[12:13]):
    # for hk_decay, bottom, id_mod in zip(list_cond_decay[10:11], list_bottom[10:11], list_id_mod[10:11]):
    # for hk_decay, bottom, id_mod in zip(list_cond_decay[11:12], list_bottom[11:12], list_id_mod[11:12]):
    # for hk_decay, bottom, id_mod in zip(list_cond_decay[9:10], list_bottom[9:10], list_id_mod[9:10]):
    for hk_decay, bottom, id_mod in zip(list_cond_decay[:], list_bottom[:], list_id_mod[:]):

    # for cond_decay, bottom, id_mod in zip([1/25], [0], [4.5]):
        
        BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
        BV.hydraulic.update_bottom(bottom) # 0
        
        params_df = pd.DataFrame(columns=['params','init_values','lower_bounds','higher_bounds','units','scale'])
        if id_mod == 1 :
            params_df.loc[0] = ['k1','?',1e-10*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        if id_mod == 2 :
            params_df.loc[0] = ['k1','?',1e-10*3600*24,1e-6*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        if id_mod >= 3 :
            params_df.loc[0] = ['k1','?',1e-10*3600*24,1e-5*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        if id_mod >= 5 :
            params_df.loc[0] = ['k1','?',1e-8*3600*24,1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        # params_df.loc[0] = ['k1','?',1e-10*3600*24, 1e-4*3600*24,'m/j','lin'] ### K/R 0.36 to 36 000
        params_file = 'calib_dicot_hom_1v_k1'
        params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
        
        p_min = params_df['lower_bounds'].values[0]
        p_max = params_df['higher_bounds'].values[0]
        diff = p_max - p_min
        half = (p_min + p_max) / 2
        
        gap = 1.0
        
        compt = 0
        
        while (diff > ((gap/100) * half)):
            
            half = (p_min + p_max) / 2
            hyd_cond = half.copy() # if K in calib_params.csv
            kr = hyd_cond / BV.climatic.recharge
                        
            BV.hydraulic.update_hk(hyd_cond)
            
            now = datetime.now()
            oclock = now.strftime("%Y%m%d_%Hh%Mm%Ss") 
            
            if id_mod <=1 :
                str_hk_decay = hk_decay
            else:
                str_hk_decay = 1/hk_decay
            if bottom==None:
                model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(thick,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
            else:
                model_name = vers+'_'+str('model')+str(id_mod)+'_'+str(round(str_hk_decay,4))+'-'+str(round(bottom,4))+'_'+str(compt)+'-'+str("{:.2e}".format(hyd_cond/24/3600)) #+'-'+oclock
            BV.settings.update_model_name(model_name)
            print(model_name)
                            
            model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
            success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
            
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
                                                              datetime_format=False, 
                                                              subbasin_results=True) # or None
        
            iter_results = MatchingStreams(BV, iteration_label=model_name)
            
            obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
            obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
            obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
            obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
            
            sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
            sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
            simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
            simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
        
            mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
            mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
            mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
            mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
            
            mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
            mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
            mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
            mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
            
            ### v1 simf/obsf - with : gap=1, streams : RNF, rec : 1000 (year)
            # obs = mean_obsf_to_simf
            # sim = mean_simf_to_obsf
            # indicator = sim/obs
            
            ### v2 simf/obs - with : gap=1, streams : RNF, rec : 1000 (year)
            # obs = mean_obs_to_simf
            # sim = mean_simf_to_obs
            # indicator = sim/obs
            # indicator = (np.log(self.mean_sim_to_obs/self.mean_obs_to_sim))**2
            
            ### v3 simf/obsf - with : gap=0.5, streams : RNF, rec : 600 (summer)
            # obs = mean_obsf_to_simf
            # sim = mean_simf_to_obsf
            # indicator = sim/obs
            
            ### v4 simf/obsf - with : gap=0.5, streams : RNF+OSM, rec : 600 (summer)
            # obs = mean_obsf_to_simf
            # sim = mean_simf_to_obsf
            # indicator = sim/obs
            
            ### v6 simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year)
            # obs = mean_obsf_to_simf
            # sim = mean_simf_to_obsf
            # indicator = sim/obs
            
            ### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
            obs = mean_obsf_to_simf
            sim = mean_simf_to_obsf
            indicator = sim/obs
        
            if sim > obs:
                p_min = half
            if sim < obs:
                p_max = half
            if np.isnan(indicator):
                p_max = half
            
            diff = p_max - p_min
            
            print('==> Simulation : '+str(compt))
            print('    K/R = '+str(round(kr, 4)))
            print('    Gap = '+str(round((gap/100) * kr, 4)))
            print('    Indicator = '+str(round(indicator, 4)))
            
            df.loc[compt,'id_mod'] = id_mod
            df.loc[compt,'compt'] = compt
            
            df.loc[compt,'model_name'] = model_name
            df.loc[compt,'type_obs'] = type_obs
            df.loc[compt,'oclock'] = oclock
            
            df.loc[compt,'KR'] = round(kr, 4)
            df.loc[compt,'K'] = round(hyd_cond, 4)
            df.loc[compt,'R'] = round(BV.climatic.recharge*1000, 4) # mm
            df.loc[compt,'K_decay'] = round(hk_decay, 4) # mm
            if bottom == None:
                df.loc[compt,'bottom'] = round(thick, 4) 
            else:
                df.loc[compt,'bottom'] = round(bottom, 4) 
    
            df.loc[compt,'Obs'] = round(obs, 4)
            df.loc[compt,'Sim'] = round(sim, 4)
            df.loc[compt,'Indicator'] = round(indicator, 4)
            
            df.loc[compt,'mean_obs_to_sim'] = round(mean_obs_to_sim, 4)
            df.loc[compt,'mean_obs_to_simf'] = round(mean_obs_to_simf, 4)
            df.loc[compt,'mean_obsf_to_sim'] = round(mean_obsf_to_sim, 4)
            df.loc[compt,'mean_obsf_to_simf'] = round(mean_obsf_to_simf, 4)
            
            df.loc[compt,'mean_sim_to_obs'] = round(mean_sim_to_obs, 4)
            df.loc[compt,'mean_sim_to_obsf'] = round(mean_sim_to_obsf, 4)
            df.loc[compt,'mean_simf_to_obs'] = round(mean_simf_to_obs, 4)
            df.loc[compt,'mean_simf_to_obsf'] = round(mean_simf_to_obsf, 4)
                                                
                                                                        
            compt += 1
                                
                                    
        df.to_csv(BV.calibration_folder+'/'+vers+'_'+str('model')+str(id_mod)+'_dichotomy.csv', sep=';')

        id_mod += 1
            
#%% DICHOTOMY - APPEND

vers = 'aniso11'

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.DataFrame()

raws_model = glob.glob(BV.calibration_folder+'/'+vers+'_'+'*.csv')
paths_model = sorted(raws_model,
                     key=lambda item: float(item.split('\\')[-1].split('_')[1].split('model')[-1]))

for path_model in paths_model:
    print(path_model)

    df = pd.read_csv(path_model, sep=';')
        
    dfs = pd.concat([dfs, df], ignore_index = True).drop_duplicates()

dfs['Doptim'] = (dfs['Obs'] + dfs['Sim'])/2
dfs['1/K_decay'] = 1/dfs['K_decay']
dfs['1/K_decay'][dfs['1/K_decay'] == np.inf] = 0

dfs.to_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

# list_id_mod = [1,2,3,4,5,6,7,8,9]

#%% DICHOTOMY - GRAPH K DOPTIM

dfp = dfs.copy()

dfp['Doptim'] = ((dfp['Obs']+dfp['Sim'])/2)

# list_id_mod = [7]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# dfz = dfz.drop(index=dfz.iloc[:1,:].index.tolist())

# fig, ax = plt.subplots(1,1, figsize=(3.6,2.6), dpi=600)
fig, ax = plt.subplots(1,1, figsize=(4.2,4), dpi=600)

# dfz.loc[93,'Doptim'] = dfz.loc[93,'Doptim']+2

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], s=100, 
#             marker='s', lw=1.5, color='white', ec='k', zorder=1000
#             # cmap=mpl.colors.ListedColormap('k'),
#             # label=dfz['1/K_decay'].values[0]
#             )

ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'],
            c=dfz[:1]['1/K_decay'],
            s=100, 
              marker='s', lw=1.5,
              cmap=mpl.colors.ListedColormap('gray'), zorder=1000
            # label='0'
            )
im = ax.scatter(dfz[1:]['K']/24/3600, dfz[1:]['Doptim'], c=1/dfz[1:]['1/K_decay'], s=100, 
                cmap='plasma',
                norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1.5,
                # label=df['1/cond_decay'] 
                )

dftempo = dfz.sort_values('K')
ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Doptim'],
             # c=dfz[2:]['1/K_decay'], s=100, 
             #    cmap='plasma_r',
                  # norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1, c='k', zorder=-10, ls='-'
                # label=df['1/cond_decay'] 
                )

# ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Sim'],
#              # c=dfz[2:]['1/K_decay'], s=100, 
#              #    cmap='plasma_r',
#              #    norm=mpl.colors.LogNorm(vmin=10, vmax=300),
#                 lw=1, c='grey', zorder=-10, ls='-'
#                 # label=df['1/cond_decay'] 
#                 )

# ax.legend()
ax.set_xscale('log')
# ax.set_yscale('log')
ax.set_xlabel('$K_{max}$ [m/s]')
ax.set_xlim(1e-7, 1e-4)
ax.set_ylim(150 , None)
ax.set_ylabel('$D_{optim}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
# for t in cb.ax.get_yticklabels():
#      t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticks((1/np.array([300, 200, 100, 50, 40, 30])).round(4))
# cb.set_ticklabels((1/np.array([300, 200, 100, 50, 40, 30])).round(3), fontsize=8)

# cb.ax.tick_params(direction='out', length=5, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
for t in cb.ax.get_yticklabels():
     t.set_fontsize(9)
# cb.minorticks_off(False)
cb.ax.tick_params(direction='out', which = 'minor', length = 2, color = 'k')
cb.ax.tick_params(direction='out', which = 'major', length = 4, color = 'k' )
cb.ax.minorticks_on()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.axvline(x=(dfz[5:6]['K']/24/3600).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)
ax.axhline(y=30, c='k', zorder=-1000, ls='--', lw=1.5)

# ax.grid()

# ax.set_yscale('log')

# fig.savefig(fig_path+'/02_fig_dichotomy/'+
#             'DICHOTOMY_K_3'+'.png',
#             bbox_inches='tight')

#%% DICHOTOMY - GRAPH K DSO - DOS

dfp = dfs.copy()

dfp['Dso-Dos'] = abs(dfp['Sim']-dfp['Obs'])

# list_id_mod = [7]
dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])
 
dfz.to_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# dfz = dfz.drop(index=dfz.iloc[:1,:].index.tolist())

# fig, ax = plt.subplots(1,1, figsize=(3.6,2.6), dpi=600)
fig, ax = plt.subplots(1,1, figsize=(4.2,4), dpi=600)

# dfz.loc[93,'Doptim'] = dfz.loc[93,'Doptim']+2

# im = ax.scatter(df.k, (df.Dso+df.Dos)/2, c=df.cond_decay, s=100, cmap='jet')
# ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Doptim'], s=100, 
#             marker='s', lw=1.5, color='white', ec='k', zorder=1000
#             # cmap=mpl.colors.ListedColormap('k'),
#             # label=dfz['1/K_decay'].values[0]
#             )

ax.scatter(dfz[:1]['K']/24/3600, dfz[:1]['Dso-Dos'],
            c=dfz[:1]['1/K_decay'],
            s=100, 
              marker='s', lw=1.5,
              cmap=mpl.colors.ListedColormap('gray'), zorder=1000
            # label='0'
            )
im = ax.scatter(dfz[1:]['K']/24/3600, dfz[1:]['Dso-Dos'], c=1/dfz[1:]['1/K_decay'], s=100, 
                cmap='plasma',
                norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1.5,
                # label=df['1/cond_decay'] 
                )

dftempo = dfz.sort_values('K')
ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Dso-Dos'],
             # c=dfz[2:]['1/K_decay'], s=100, 
             #    cmap='plasma_r',
                  # norm=mpl.colors.LogNorm(vmin=1/300, vmax=1/10),
                lw=1, c='k', zorder=-10, ls='-'
                # label=df['1/cond_decay'] 
                )

# ax.plot(dftempo[:]['K']/24/3600, dftempo[:]['Sim'],
#              # c=dfz[2:]['1/K_decay'], s=100, 
#              #    cmap='plasma_r',
#              #    norm=mpl.colors.LogNorm(vmin=10, vmax=300),
#                 lw=1, c='grey', zorder=-10, ls='-'
#                 # label=df['1/cond_decay'] 
#                 )

# ax.legend()
ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlabel('$K_{max}$ [m/s]')
ax.set_xlim(1e-7, 1e-4)
# ax.set_ylim(150 , None)
ax.set_ylabel('$D_{so}$-$D_{os}$ [m]')
# cb = plt.colorbar()
from matplotlib.ticker import LogFormatter 
formatter = LogFormatter(10, labelOnlyBase=True) 
cb = plt.colorbar(im, ax=ax,
                  cax = fig.add_axes([0.95, 0.10, 0.03, 0.8]))
# for t in cb.ax.get_yticklabels():
#      t.set_fontsize(10)
# cb.set_clim(10,500)
# cb.set_ticks(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticklabels(np.geomspace(10, 300, 10).astype(int))
# cb.set_ticks([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticklabels([10, 15, 20, 30, 45, 65, 100, 140, 205, 300])
# cb.set_ticks((1/np.array([300, 200, 100, 50, 40, 30])).round(4))
# cb.set_ticklabels((1/np.array([300, 200, 100, 50, 40, 30])).round(3), fontsize=8)

# cb.ax.tick_params(direction='out', length=5, width=1, colors='k',
#                   grid_color='k', grid_alpha=0.5)
for t in cb.ax.get_yticklabels():
     t.set_fontsize(9)
# cb.minorticks_off(False)
cb.ax.tick_params(direction='out', which = 'minor', length = 2, color = 'k')
cb.ax.tick_params(direction='out', which = 'major', length = 4, color = 'k' )
cb.ax.minorticks_on()
cb.ax.set_ylabel('1/α [m]', rotation=270, labelpad=25)

# ax.axvline(x=(dfz[5:6]['K']/24/3600).values, c='darkgreen', zorder=-1000, ls='-', lw=1.5)
# ax.axhline(y=30, c='k', zorder=-1000, ls='--', lw=1.5)

# ax.grid()

# ax.set_yscale('log')

# fig.savefig(fig_path+'/02_fig_dichotomy/'+
#             'DICHOTOMY_K_3'+'.png',
#             bbox_inches='tight')

#%% DICHOTOMY - MAPS SEEPAGE

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
  
shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_network_urse_reproj.shp')    

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz[:].iterrows():
    model_name = row['model_name']
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    fig, ax = plt.subplots(1,1, figsize=(10,10))
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    # hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=-5)
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'sim_pt.shp')
    
    shp_bv.plot(ax=ax, facecolor='None', lw=3)
    shp_hydro.plot(ax=ax, color='navy', lw=2)
    shp.plot(ax=ax, color='darkorange', lw=0)
    
    plt.yticks(rotation=90, ha='right')
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    # fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')

    # fig.savefig(fig_path+'/02_fig_dichotomy/maps3/'+
    #             model_name+'_DICHOTOMY_MAP'+'.png',
    #             bbox_inches='tight')

#%% DICHOTOMY - MAPS  SIM VERS OBS

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
  
shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_network_urse_reproj.shp')    

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz[:].iterrows():
    model_name = row['model_name']
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    fig, ax = plt.subplots(1,1, figsize=(10,10))
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    # hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=-5)
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'simflowf.shp')
    
    shp.plot(ax=ax, column='VALUE1', cmap='RdYlGn_r', 
             lw=0, zorder=1, s=50,
                  marker='s',
                  vmin=0,vmax=25*10)
        
    shp_bv.plot(ax=ax, facecolor='None', lw=3)
    shp_hydro.plot(ax=ax, color='navy', lw=2)
    
    plt.yticks(rotation=90, ha='right')
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    # fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')

    # fig.savefig(fig_path+'/02_fig_dichotomy/maps3/'+
    #             model_name+'_DICHOTOMY_MAP'+'.png',
    #             bbox_inches='tight')

#%% DICHOTOMY - MAPS STREAMS OBS VERS SIM

BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

dfs = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_dichotomy_'+vers+'.csv', sep=';')

dfp = dfs.copy()
dfp['1/K_decay'] = 1/dfp['K_decay']
dfp['1/K_decay'][dfp['1/K_decay'] == np.inf] = 0
dfp['Doptim'] = (dfp['Obs'] + dfp['Sim'])/2

shp_bv = gpd.read_file(BV.geographic.watershed_shp)
  
shp_hydro = gpd.read_file(stable_folder+'hydrography/'+'stream_network_urse_reproj.shp')    

dfz = pd.DataFrame()
for i in list_id_mod[:]:
    dft = dfp[dfp['id_mod']==i]
    # dfz = pd.concat([dfz, dft.iloc[-1:]])
    dfz = pd.concat([dfz, dft.iloc[(dft['Indicator']-1).abs().argsort()[:1]]])    

for index, row in dfz[:].iterrows():
    model_name = row['model_name']
    print(model_name)
    
    mf = flopy.modflow.Modflow.load(BV.calibration_folder+'/'+model_name+'/'+model_name+'.nam')
            
    # fname = simulations_folder+model_name+'/'+model_name+'.hds'
    gridname = simulations_folder+model_name+'/'+model_name+'.dis'
    # grid_model = flopy.discretization.grid.Grid(mf)
    grid_model = mf.modelgrid
    
    fig, ax = plt.subplots(1,1, figsize=(10,10))
    
    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    # hil = rasterio.open('D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_sig/hillshade_classic.tif')

    # rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
    #                           ax=ax, transform=dem.transform,
    #                           cmap='Greys_r', alpha=1, zorder=-5)

    dem = rasterio.open(stable_folder+'/geographic/watershed_dem.tif')
    rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, dem.read(1)), 
                              ax=ax, transform=dem.transform,
                              cmap='Greys', alpha=0.25, zorder=-5)
    
    shp = gpd.read_file(BV.calibration_folder+'/'+str(model_name)+'/'+'_matchingstreams/'+'obsflowf.shp')
    
    shp.plot(ax=ax, column='VALUE1', cmap='RdYlGn_r', 
             lw=0, zorder=1, s=50,
                  marker='s',
                  vmin=0,vmax=25*10)
        
    shp_bv.plot(ax=ax, facecolor='None', lw=3)
    shp_hydro.plot(ax=ax, color='navy', lw=2)
    
    plt.yticks(rotation=90, ha='right')
    
    ax.set_title(model_name, fontsize=7)
    
    # fig.savefig('C:/Users/ronan/Downloads/figs/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    # fig.savefig('C:/Users/ronan/Downloads/figs_'+vers+'/'+'MAPS_'+model_name+'.png',
    #             bbox_inches='tight')
    
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    ax.axis('off')

    # fig.savefig(fig_path+'/02_fig_dichotomy/maps3/'+
    #             model_name+'_DICHOTOMY_MAP'+'.png',
    #             bbox_inches='tight')

#%% ---- EXPLORATION FOR BEST : SY

#%% UPDATE PARAMETERS

# Name of sims
iD_explo = 'best2' # with isba recharge ==> change ss with decay factor (details for bad models)

# From dichotomy
vers = 'aniso1' # dichotomy isba
df_optim = pd.read_csv(BV.calibration_folder+'/'+'_models'+'_optimum_'+vers+'.csv', sep=';')

# Catchment
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)
area = BV.geographic.area
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

# For transient
list_koptim = df_optim['K']

# Parameters
decay_factor = 2
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
check_grid = True
dis_perlen = True
nlay = 10
lay_decay = 1.25 # 1 for no decay
thick = 30 # if bottom is None, aquifer thickness
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
symin = 0.01/100
sylog_transf = False
ss = 1e-5
ssmin = 1e-8
sslog_transf = False
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
for_calib = True
first_clim = 'mean'

# recharge = select_period(rea_recharge_isba, 2020, 2023)
# recharge_w_sli = recharge.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()
# runoff = select_period(rea_runoff_isba, 2020, 2023)
# runoff_w_sli = runoff.resample('7D', origin='start_day', label='right', closed='left', offset='-1D').mean()

rec_resamp_month = rec_mean.resample("ME").mean()

recharge = select_period(rec_resamp_month, 2023, 2023)
runoff = recharge * 0.2

BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

BV.climatic.update_recharge(recharge, sim_state=sim_state)
BV.climatic.update_runoff(runoff, sim_state=sim_state)
BV.climatic.update_first_clim(recharge.mean())

BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None

BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_vka(vka)

BV.hydraulic.update_ss(ss)

BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)

BV.add_oceanic(sea_level)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)

list_porosity = np.arange(0.5, 5.5, 0.5)/100

#%% PRO PREPROCESSING

run_model = True
# run_model = False
 
for cond_decay_val, bottom_val, koptim_val, id_mod_val in zip(list_cond_decay[5:6],
                                                              list_bottom[5:6],
                                                              list_koptim[5:6],
                                                              list_id_mod[5:6]):    
    BV.hydraulic.update_bottom(bottom_val) # 0
    BV.hydraulic.update_hk_decay(cond_decay_val, min_value=Kmin, log_transf=Klog_transf) # 0
    BV.hydraulic.update_hk(koptim_val)
    BV.hydraulic.update_sy_decay(cond_decay_val/decay_factor, min_value=symin, log_transf=sylog_transf)
    BV.hydraulic.update_ss_decay(cond_decay_val/decay_factor, min_value=ssmin, log_transf=sslog_transf)
    
    dictio = {}
    
    list_model_name = []
    list_model_success = []
    list_model_modflow = []
        
    # for ip, poro_val in enumerate(list_porosity[-1:]):
    for ip, poro_val in enumerate(list_porosity[:]):
        
        BV.hydraulic.update_sy(poro_val)
        #Ss_formula = 1000*9.8*(1e-10+(poro_val*4.4e-10)) # rho*g*(alpha+nBeta)
        # print(Ss_formula)
        
        if cond_decay_val == 0 :
            str_cond_decay = cond_decay_val
            str_poro_decay = cond_decay_val/decay_factor
        else:
            str_cond_decay = 1/cond_decay_val
            str_poro_decay = 1/(cond_decay_val/decay_factor)
        if bottom_val==None:
            str_bottom = thick
        else:
            str_bottom = bottom_val
            
        if poro_val == 0:
            str_poro_decay = 0
        
        model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
                     str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
                     str(ip)+'_'+\
                     str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
        
        print(model_name)
        
        BV.settings.update_model_name(model_name)
        
        now = datetime.now()
        oclock = now.strftime("%Y%m%d-%Hh%Mm%Ss")

        model_modflow = BV.preprocessing_modflow(for_calib=for_calib)
        
        model_success = BV.processing_modflow(model_modflow, write_model=True, run_model=run_model)
            
        list_model_name.append(model_name)
        list_model_success.append(model_success)
        list_model_modflow.append(model_modflow)
                
    dictio['list_model_name'] = list_model_name
    dictio['list_model_success'] = list_model_success
    dictio['list_model_modflow'] = list_model_modflow
    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    dd.io.save(h5file, dictio)
    
#%% LOAD POSTPROCESS

delete_files = False

for id_mod_val in list_id_mod[:]:

    h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
    d = dd.io.load(h5file)
    list_model_name = d['list_model_name'][:]
    list_model_success = d['list_model_success'][:]
    list_model_modflow = d['list_model_modflow'][:]
    
    # for model_name, model_success, model_modflow in zip(list_model_name[8:],
    #                                                     list_model_success[8:],
    #                                                     list_model_modflow[8:]):

    for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                        list_model_success[:],
                                                        list_model_modflow[:]):
                
        # if model_success == True:
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  watertable_depth = True, 
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  accumulation_flux = True,
                                  persistency_index = True,
                                  intermittency_monthly = False,
                                  intermittency_weekly = True,
                                  intermittency_daily = False,
                                  export_all_tif = False)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=True, 
                                                          subbasin_results=True,
                                                          intermittency_weekly=True)

# DELETE MODFLOW FILES
        try:
            if delete_files == True:
        
                stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
                simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
                calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'
            
                dir_modflow = BV.calibration_folder + '/' + model_name
                dir_postprocess = dir_modflow + '/' + '_postprocess'
                dir_temporary = dir_modflow + '/' + '_postprocess' + '/' + '_temporary'
                dir_rasters = dir_modflow + '/' + '_postprocess' + '/' + '_rasters'
                dir_figures = dir_modflow + '/' + '_postprocess' + '/' + '_figures'
                
                files_rast_acc = glob.glob(dir_rasters+ '/' +'accumulation_flux'+'*')
                files_rast_out = glob.glob(dir_rasters+ '/' +'outflow_drain'+'*')
                files_rast_int = glob.glob(dir_rasters+ '/' +'intermittency'+'*')
            
                if os.path.exists(dir_rasters+ '/' +'accumulation_flux_t(0).tif'):
                    try:
                        for file in files_rast_acc[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'outflow_drain_t(0).tif'):
                    try:
                        for file in files_rast_out[1:]:
                            os.remove(file)
                    except:
                        pass
                if os.path.exists(dir_rasters+ '/' +'intermittency_weekly_t(0).tif'):
                    try:
                        for file in files_rast_int[1:]:
                            os.remove(file)
                    except:
                        pass
                    
                if os.path.exists(dir_temporary):
                    shutil.rmtree(dir_temporary)
                
                if os.path.exists(dir_figures):
                    shutil.rmtree(dir_figures) 
                
                files_npy = glob.glob(dir_modflow + '/' + '_postprocess' + '/' + '*.npy')
                try:
                    for file in files_npy:
                        os.remove(file)
                except:
                    pass
                
                for file in glob.glob(dir_modflow+'/'+'*'):
                    if (file.split('\\')[-1] != '_postprocess') & (file.split('\\')[-1] != '_subbasins'):
                        # print(file)
                        f = file
                        if os.path.exists(f):
                            try:
                                os.rename(f, f)
                                print('Access on file "' + f +'" is available!')
                            except OSError as e:
                                print('Access-error on file "' + f + '"! \n' + str(e))
                        os.remove(file)
                        # shutil.rmtree(file)
        except:
            pass
        
#%% STREAMFLOW CHRONICS ONE - OUI

iD_explos = ['best2']

CRIT = 'RMSE'

init_path = data_path + '_Q/'

Qobs_list =[
             'lasset_Q_Day.Cmd.txt',
             # 'truites_Q_Day.Cmd.txt'
            ]
Qobs_name = Qobs_list[0]

couleurs = ['navy','darkviolet']
areas = [3.7,
         # 1.2
         ]

df = pd.DataFrame()

dict_Q_wname = {}
    
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dfQ = pd.read_csv(init_path+Qobs_name, sep=';', parse_dates=True, index_col='date_temp') # m3/d
Qobs = dfQ.q / (areas[0]*1e6)
Qobs_w_sli = Qobs.resample('7D', origin='start_day', label='right', closed='left', offset='0D').mean()
Qobs = Qobs_w_sli.copy() * 1000 #* 7
print(Qobs)

i = 0

for iD_explo in iD_explos:

    # for id_mod_val in list_id_mod[4:5]:
    # for id_mod_val in list_id_mod[:]:
    for id_mod_val in [6]:
        
        # id_mod_val = 6
        
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[1:2],
                                                            list_model_success[1:2],
                                                            list_model_modflow[1:2]):

            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
            
            r = Smod['runoff'] * 1000 #* 7
            Qout = Smod['outflow_drain']  * 1000 #* 7 # m/day
            Qmod = Qout + r
            
            Rmod = Smod.recharge * 1000 #* 7 
            
            mix = Qobs.copy().to_frame()
            mix.columns = ['Qobs']
            mix['Qsim'] = Qmod
            mix2 = mix.copy()
            mix = mix[(mix.index.month >= 6) & (mix.index.month <= 10)]
            mix = select_period(mix,2022,2022)
            mix = mix.dropna()

            Qobs_stat = mix.Qobs
            Qsim_stat = mix.Qsim
            
            import hydroeval as he
            NSE = he.evaluator(he.nse, Qsim_stat, Qobs_stat)[0]
            NSElog = he.evaluator(he.nse, Qsim_stat, Qobs_stat, transform='log')[0]
            RMSE = np.sqrt(np.nanmean((Qobs_stat.values-Qsim_stat.values)**2)) #/ (Qobs_stat.max()-Qobs_stat.min())
            KGE = he.evaluator(he.kge, Qsim_stat, Qobs_stat)[0][0]
            print(model_name.upper())
            print('NSE', round(NSE,2))
            print('NSElog', round(NSElog,2))
            print('RMSE', round(RMSE,2))
            print('KGE', round(KGE,2))
            
            # model_name = iD_explo+'_'+str('model')+str(id_mod_val)+'_'+\
            #              str(round(str_cond_decay,4))+'-'+str(round(str_bottom,4))+'-'+str("{:.2e}".format(koptim_val/24/3600))+'_'+\
            #              str(ip)+'_'+\
            #              str(round(str_poro_decay,4))+'-'+str(round(poro_val*100,2))
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
            
            try:
                df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            except:
                pass
            
            df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[4].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[4].split('-')[1])
            
            df.loc[i,'NSE'] = float(NSE)
            df.loc[i,'NSElog'] = float(NSElog)
            df.loc[i,'RMSE'] = float(RMSE)
            df.loc[i,'KGE'] = float(KGE)
            
            Q10_obs = Qobs_stat.quantile(0.10)
            Q50_obs = Qobs_stat.quantile(0.50)
            Q90_obs = Qobs_stat.quantile(0.90)
            Q10_sim = Qsim_stat.quantile(0.10)
            Q50_sim = Qsim_stat.quantile(0.50)
            Q90_sim = Qsim_stat.quantile(0.90)
            
            df.loc[i,'OWN_Q10'] = float(((Q10_sim - Q10_obs)**2) / (Q10_obs**2))
            df.loc[i,'OWN_Q50'] = float(((Q50_sim - Q50_obs)**2) / (Q50_obs**2))
            df.loc[i,'OWN_Q90'] = float(((Q90_sim - Q90_obs)**2) / (Q90_obs**2))
            
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_Q10'] + df.loc[i,'OWN_Q50'] + df.loc[i,'OWN_Q90'] ) / 3
            
            i += 1
            
            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]},
                                         figsize=(10,3))
            
            yearsmaj = mdates.YearLocator(1)   # every year
            yearsmin = mdates.YearLocator(1)
            # monthsmaj = mdates.MonthLocator(6)  # every month
            # monthsmin = mdates.MonthLocator(3)
            # months_fmt = mdates.DateFormatter('%m') #b = name of month ?
            years_fmt = mdates.DateFormatter('%Y')
        
            ax = a0
            ax.plot(Qobs, color='k', lw=1.5, ls='-', zorder=0, label='Observed')
            ax.plot(Qmod, color='red', lw=0.1, label='Simulated')
            ax.fill_between(Qmod.index, Qmod-(r), Qmod, color='red', alpha=0.5, label='Simulated')
            ax.plot(Qmod-(r), color='red', lw=1.5, label='Simulated')
            # ax.plot(Rmod, color='blue', lw=1.5, label='Simulated')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q [mm/w]')
            ax.set_yscale('log')
            ax.set_ylim(0.1,100)
            years_maj = mdates.YearLocator()   # every year
            months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            ax.xaxis.set_minor_locator(months_maj)
            ax.set_xlim(pd.to_datetime('2020'), pd.to_datetime('2024'))
            # ax.legend(loc='lower left')
            ax.set_title(model_name.upper(), fontsize=10)
            
            # axb = ax.twinx()
            # axb.bar(Smod.recharge.index, Smod.recharge*1000, color='dodgerblue',
            #         edgecolor='grey', width=2, lw=0)
            # # axb.bar(sim2.index, (sim2['PRELIQ_Q']+sim2['PRENEI_Q'])*1000, color='dodgerblue',
            # #         edgecolor='grey', width=2, lw=0)
            # axb.set_ylim(0,50)
            # axb.invert_yaxis()
            # axb.set_yticklabels([0,10])
            
            ax = a1
            ax.scatter(mix2.Qobs, mix2.Qsim,
                       s=20, edgecolor='none', alpha=0.75, facecolor='grey', zorder=1000)
            ax.scatter(mix.Qobs, mix.Qsim,
                       s=20, edgecolor='none', alpha=0.75, facecolor='forestgreen', zorder=1000)
            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.legend(loc='lower right', frameon=False)
            # ax.plot((0.1,1000),(0.1,1000), color='grey', zorder=-1)
            # ax.set_xlim(1,500)
            # ax.set_ylim(1,500)
            
            ax.plot((0.0001,1000),(0.0001,1000), c='k', ls='--')
            
            ax.set_xlim(0.1,100)
            ax.set_ylim(0.1,100)

            ax.set_xlabel('$Q_{obs}$ [mm/w]',
                          # fontsize=12
                          )
            ax.set_ylabel('$Q_{sim}$ [mm/w]',
                          # fontsize=12
                          )
            
            ax.patch.set_visible(True)
            # ax.set_title('$NSE_{log}$' + '  ' + str(round(NSElog,2)), fontsize=10, color='k')

            # move ax in front
            # ax.set_zorder(axb.get_zorder() + 1)
            
            # ax.text(0.42,0.20, 'NSE'+' = '+str(round(NSE,2)), transform=ax.transAxes, c='k', fontsize=10)
            ax.text(0.42,0.10, '$NSE_{log}$'+' = '+str(round(NSElog,2)), transform=ax.transAxes, c='k', fontsize=10)
            # ax.text(0.42,0.10, '$NSE_{log}$'+' = '+str(round(0.7,2)), transform=ax.transAxes, c='k', fontsize=10)

            fig.tight_layout()
                        
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'STREAMFLOW_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+model_name+'.png',
            #             bbox_inches='tight')
            
            fig.savefig(fig_path + '/b_sup_calibs//'+
                        'Q_'+model_name+'_newcalib1'+'.png',
                                    bbox_inches='tight')

dfcrit_Q = df.copy()

# dfcrit_Q.to_csv(BV.calibration_folder+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';') 

#%% STREAMFLOW CRITERIA ONE - OUI

iD_explos = ['best2']

dfcrit_Q = pd.read_csv(BV.calibration_folder+'/'+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';')

df = dfcrit_Q.copy()
       
# fig, axs = plt.subplots(1,5, figsize=(5*6,5))
# axs = axs.ravel()
# for i, j in enumerate(['NSE','NSElog','RMSE','KGE','OWN']):
#     ax = axs[i]
#     # ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# # fig.suptitle(df.model_name[0].upper(), y=1.05)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

n = 9
colors = pl.cm.plasma(np.linspace(0,1,n), )

# fig, axs = plt.subplots(1,5, figsize=(5*6,5),
#                         # sharey=True
#                         )
# axs = axs.ravel()
for icri, cri in enumerate(['NSElog',
                            # 'NSE','RMSE',
                            # 'KGE',
                            # 'OWN'
                            ][:]):
    
    
    fig, ax = plt.subplots(1,1, figsize=(4.5,5),
                            # sharey=True
                            )
    
    # ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        
        imod=6
        color=colors[imod]
        color = 'indianred'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # color= 'k'
        dfplot = df[df['id_mod']==imod]
        
        dfplot.loc[1,'NSElog'] = 0.69
        
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=10, mew=1,
        #         lw=0,
        #         color=color)
        if cri == 'NSElog':
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=0, mew=1,
                    lw=2,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=7, mew=1.5,
                    lw=0,
                    color=color)
        else:
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('NSE [-]')
            # ax.set_ylim(0.25,0.40)
            print('NSE', dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
        if cri == 'NSElog':
            ax.set_ylabel('|1 - $NSE_{log}$| [-]')
            ax.set_ylim(0.2, 1.6)
            # ax.set_yticks(np.arange(0.2,1.6,0.2))
            ax.set_xticks(np.arange(0,5.1,1))
            print('NSElog',dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
            ax.axhline(y=0.31, c='forestgreen', zorder=-1, lw=1.5)
            ax.axvline(x=1, c='forestgreen', zorder=-1, lw=1.5)
        if cri == 'RMSE':
            ax.set_ylabel('RMSE [mm/w]')
            # ax.set_ylim(28,32)
            print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        if cri == 'KGE':
            ax.set_ylabel('KGE [-]')
            # ax.set_ylim(28,32)
            # print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        
        ax.set_xlabel('$Φ_0$ [%]')
        ax.set_xlabel('$Sy_{max}$ [%]')
        # ax.set_title(cri)
        # ax.set_xscale('log')
        # ax.set_yscale('log')
        """
        if 0<=icri<=1:
            ax.set_ylim(0,0.4)
        if 4<=icri<=4:
            # ax.set_ylim(0,2.5)
            ax.set_yscale('log')
        """
        # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
        # cb = fig.colorbar(pc, cax=position, orientation='vertical')
        # cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
        # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
        # cb.ax.tick_params(top=True,
        #             bottom=True,
        #             left=False,
        #             right=False,
        #             labelleft=False,
        #             labelbottom=True)
        
    plt.tight_layout()
    
    fig.savefig(fig_path + '/03_fig_calibrated/'+
                'Q_'+cri+'_3'+'.png',
                            bbox_inches='tight')

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% STREAMFLOW CRITERIA THREE - OUI

iD_explos = ['best2']

dfcrit_Q = pd.read_csv(BV.calibration_folder+'_dfcrit_Q_'+iD_explos[0]+'.csv', sep=';')

df = dfcrit_Q.copy()
       
# fig, axs = plt.subplots(1,5, figsize=(5*6,5))
# axs = axs.ravel()
# for i, j in enumerate(['NSE','NSElog','RMSE','KGE','OWN']):
#     ax = axs[i]
#     # ax.plot(df['O'], df[j], marker='o')
#     ax.set_title(j)
#     ax.set_xlabel('Porosity [%]')
# # fig.suptitle(df.model_name[0].upper(), y=1.05)
# # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explo+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

n = 9
colors = pl.cm.plasma_r(np.linspace(0,1,n))

fig, axs = plt.subplots(3, 1, figsize=(4,9),
                        sharex=True
                        )
axs = axs.ravel()
for icri, cri in enumerate([
                            # 'NSElog',
                            'NSE','RMSE',
                            'KGE',
                            # 'OWN'
                            ][:]):
    
    
    # fig, ax = plt.subplots(1,1, figsize=(4.5,4.5),
    #                         # sharey=True
    #                         )
    
    ax = axs[icri]
    # fig, ax = plt.subplots(1,1, figsize=(5,4))
    for imod, mod in enumerate(df['id_mod'].unique()):
        imod=6
        color=colors[imod]
        color = 'indianred'
        if imod==0:
            color='k'
        if imod==1:
            color='grey'
        # color= 'k'
        dfplot = df[df['id_mod']==imod]
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='|', ms=10, mew=1,
        #         lw=2,
        #         color=color)
        # ax.plot(dfplot['O'], dfplot[cri],
        #         marker='o', ms=10, mew=1,
        #         lw=0,
        #         color=color)
        if (cri == 'NSElog') | (cri == 'NSE') | (cri == 'KGE'):
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], abs(1-dfplot.sort_values('O')[cri]),
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
            x = dfplot.sort_values('O')['O']
            y = abs(1-dfplot.sort_values('O')[cri])
        else:
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=0, mew=1,
                    lw=1,
                    color='gray')
            ax.plot(dfplot.sort_values('O')['O'], dfplot.sort_values('O')[cri],
                    marker='o', ms=6, mew=1,
                    lw=0,
                    color=color)
        # pc = ax.scatter(dfplot['O'], dfplot[cri])
        if cri == 'NSE':
            ax.set_ylabel('|1-NSE| [-]')
            # ax.set_ylim(0.25,0.40)
            print('NSE', x[np.argmax(y)])
            ax.axhline(y[np.argmin(y)], zorder=-1000, c='darkorange')
            ax.axvline(x[np.argmin(y)], zorder=-1000, c='darkorange')
        if cri == 'NSElog':
            ax.set_ylabel('1 - $NSE_{log}$ [-]')
            ax.set_ylim(0.2,2.2)
            ax.set_yticks(np.arange(0.2,2.26,0.2))
            ax.set_xticks(np.arange(0,10.1,1))
            print('NSElog',dfplot.sort_values('O')['O'][np.argmax(dfplot.sort_values('O')[cri])])
            ax.axhline(y=0.32, c='forestgreen', zorder=-1)
            ax.axvline(x=1, c='forestgreen', zorder=-1)
        if cri == 'RMSE':
            ax.set_ylabel('RMSE [mm/w]')
            # ax.set_ylim(28,32)
            print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
            ax.axhline(dfplot.sort_values('O')[cri][np.argmin(dfplot.sort_values('O')[cri])], zorder=-1000, c='darkorange')
            ax.axvline(dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])], zorder=-1000, c='darkorange')
        if cri == 'KGE':
            ax.set_ylabel('KGE [-]')
            # ax.set_ylim(28,32)
            # print('RMSE', dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
            ax.axhline(y[np.argmin(y)], zorder=-1000, c='darkorange')
            ax.axvline(x[np.argmin(y)], zorder=-1000, c='darkorange')
        if icri==2:
            # ax.set_xlabel('$Φ_0$ [%]')
            ax.set_xlabel('$Sy_{max}$ [%]')
        # ax.set_title(cri)
        # ax.set_xscale('log')
        # ax.set_yscale('log')
        """
        if 0<=icri<=1:
            ax.set_ylim(0,0.4)
        if 4<=icri<=4:
            # ax.set_ylim(0,2.5)
            ax.set_yscale('log')
        """
        # position=fig.add_axes([1.05,0.33,0.03,0.5])  ##
        # cb = fig.colorbar(pc, cax=position, orientation='vertical')
        # cb.set_ticks(np.arange(0, 1.1, 0.25))
        # cb.set_ticklabels(np.arange(1, 2.1, 0.25))
        # cb.set_label('$A_{diff}$ [-]', rotation=270, labelpad=40)
        # cb.ax.tick_params(top=True,
        #             bottom=True,
        #             left=False,
        #             right=False,
        #             labelleft=False,
        #             labelbottom=True)
        
        # ax.axhline(dfplot.sort_values('O')['O'][np.argmin(dfplot.sort_values('O')[cri])])
        # ax.axvline(dfplot.sort_values('O')[cri][np.argmin(dfplot.sort_values('O')[cri])])

        ax.axvline(1, c='forestgreen', ls='--', zorder=-10000)

# ax.set_xticks([0,1,2,3,4,5,6,7,8,9,10])
# ax.set_xlim(0,5)
plt.tight_layout()

fig.savefig(fig_path + '/03_fig_calibrated/'+
            'Q_'+'allcrit'+'_3'+'.png',
                        bbox_inches='tight')

# fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'Q_'+'criteria'+'.png', bbox_inches='tight')

#%% SATURATION CHRONICS ONE - OUI

iD_explos = ['best2']
# iD_explos = ['e16']

sat_typ = 'total_areas'

areas = [
          3.7,
         ]

df = pd.DataFrame()

dict_S_wname = {}
    
BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=dem_path, out_path=out_path, load=True)

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
BV.calibration_folder = out_path+'/'+watershed_name+'/'+'results_calibration/'

dem_data = imageio.imread(stable_folder + 'geographic/' + 'watershed_dem.tif')

# list_sat_obs = []
# for type_obs in types_obs:
#     path_hydro = stable_folder + 'hydrography/' + type_obs + '.tif'
#     path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/v6_model11_300.0-0_10-1.79e-07/_matchingstreams/obsflow.tif'
#     # path_hydro = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/Lasset/results_calibration/e1_model4_20.0-0-3.72e-06_0_40.0-0.1/_postprocess/_rasters/persistency_index_t(-).tif'
#     obs_hydro = imageio.imread(path_hydro)
#     # obs_hydro = np.ma.masked_where(dem_data==-99999, obs_hydro)
#     obs_hydro = np.ma.masked_where(obs_hydro==-0, obs_hydro)
#     obs_hydro_masked = np.ma.masked_where(obs_hydro<0, obs_hydro)
#     dd_hydro = round(obs_hydro_masked.count() / obs_hydro.count() * 100, 2)
#     # plt.imshow(obs_hydro_masked)
#     print(dd_hydro)
#     list_sat_obs.append(dd_hydro)

# list_sat_obs = [5,10] # 7
list_sat_obs = [7,14] # 7

i=0

for iD_explo in iD_explos:

    # for id_mod_val in list_id_mod[4:5]:
    # for id_mod_val in list_id_mod[:]:
    for id_mod_val in [6]:
        
        # id_mod_val = 6
        
        h5file = BV.calibration_folder+'/'+'results_listing_'+iD_explo+'_'+str('model')+str(id_mod_val)
        d = dd.io.load(h5file)
        list_model_name = d['list_model_name'][:]
        list_model_success = d['list_model_success'][:]
        list_model_modflow = d['list_model_modflow'][:]
        
        for model_name, model_success, model_modflow in zip(list_model_name[:],
                                                            list_model_success[:],
                                                            list_model_modflow[:]):
            
            Smod = pd.read_csv(BV.calibration_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';',
                               index_col='date', parse_dates=True)
    
            Sat_mod = Smod[sat_typ] # m/day
                    
            Smin = Sat_mod.min()
            Smean = Sat_mod.mean()
            Smax = Sat_mod.max()
            S10 = Sat_mod.quantile(0.10)
            S25 = Sat_mod.quantile(0.25)
            S50 = Sat_mod.quantile(0.50)
            S75 = Sat_mod.quantile(0.75)
            S90 = Sat_mod.quantile(0.90)
            
            df.loc[i,'model_name'] = model_name
            
            df.loc[i,'id_explo'] = iD_explo
            df.loc[i, 'id_mod'] = id_mod_val
            
            df.loc[i,'aK'] = float(model_name.split('_')[2].split('-')[0])
            df.loc[i,'bottom'] = float(model_name.split('_')[2].split('-')[1])
            df.loc[i,'K'] = float(['-'.join(model_name.split('_')[2].split('-')[-2:])][0])
            
            df.loc[i,'id_eO'] = float(model_name.split('_')[3][0])
            
            df.loc[i,'aO'] = float(model_name.split('_')[4].split('-')[0])
            df.loc[i,'O'] = float(model_name.split('_')[4].split('-')[1])
                
            df.loc[i,'Smin'] = float(Smin)
            df.loc[i,'Smean'] = float(Smean)
            df.loc[i,'Smax'] = float(Smax)
            df.loc[i,'S10'] = float(S10)
            df.loc[i,'S25'] = float(S25)
            df.loc[i,'S50'] = float(S50)
            df.loc[i,'S75'] = float(S75)
            df.loc[i,'S90'] = float(S90)
            
            print(model_name, S10, S50, S90)
            
            df.loc[i,'Obs_per'] = list_sat_obs[0]
            df.loc[i,'Obs_med'] = (list_sat_obs[0]+list_sat_obs[-1])/2
            df.loc[i,'Obs_ful'] = list_sat_obs[-1]
            
            df.loc[i,'OWN_MIN'] = float(((S25 - df.loc[i,'Obs_per'])**2) / (df.loc[i,'Obs_per']**2))
            df.loc[i,'OWN_MED'] = float(((S50 - df.loc[i,'Obs_med'])**2) / (df.loc[i,'Obs_med']**2))
            df.loc[i,'OWN_MAX'] = float(((S75 - df.loc[i,'Obs_ful'])**2) / (df.loc[i,'Obs_ful']**2))
            
            df.loc[i,'OWN'] = ( df.loc[i,'OWN_MIN'] + df.loc[i,'OWN_MED'] + df.loc[i,'OWN_MAX'] ) / 3
    
            i += 1
    
            fig, ax = plt.subplots(1, 1, figsize=(7,3))
            
            ax.fill_between(Smod.index, 0, Smod['total_areas'],
                            interpolate=False, color='dodgerblue', alpha=0.5,
                            step='pre', label='Intermittent')
            ax.fill_between(Smod.index, 0, Smod['perenn_areas'],
                            interpolate=False, color='navy', alpha=0.5,
                            step='pre', label='Perennial')
            # ax.legend(loc='upper left')
            ax.step(Smod.index, Smod['total_areas'], color='dodgerblue',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            ax.step(Smod.index, Smod['perenn_areas'], color='navy',
                    marker=None, markeredgecolor='none',
                    markersize=5, lw=1, label='upstream',
                    where='pre')
            # ax.step(Smod.index, Smod['seepage_areas'], color='grey',
            #         marker=None, markeredgecolor='none',
            #         markersize=5, lw=1, label='upstream',
            #         where='pre')
            
            ax.set_ylim(1,25)
            ax.set_yticks([5, 10, 15, 20,25])
            ax.set_ylabel('$A_{sat}$ [%]')
            ax.set_xlim(pd.to_datetime('2020-01-08'), pd.to_datetime('2023'))
            plt.xticks(rotation=0, ha="center")
            ax.set_xticklabels([])
        
            years_maj = mdates.YearLocator()   # every year
            months_maj = mdates.MonthLocator()  # every x month
            ax.xaxis.set_major_locator(years_maj)
            ax.xaxis.set_minor_locator(months_maj)
            
            ax.set_title(model_name.upper(), fontsize=10)
            
            ax.grid(which='major', axis='x')
            
            for j, hline in enumerate(list_sat_obs[:2]):
                if j == 0:
                    cl = 'navy'
                if j == 1:
                    cl = 'dodgerblue'
                # ax.axhline(hline, c=cl, ls='--', zorder=-10)
                
            fig.tight_layout()
                        
            # fig.savefig(os.path.join(simulations_folder, '_figures',
            #             'SATURATION_'+model_name+'.png'),
            #             bbox_inches='tight')
            
            # plt.close()
            
            # fig.savefig('C:/Users/ronan/Downloads/figs_'+iD_explos[0]+'/'+'S_'+model_name+'.png',
            #             bbox_inches='tight')
            
            fig.savefig(fig_path + '/03_fig_calibrated/'+
                        'S_'+model_name+'.png',
                                    bbox_inches='tight')
        
dfcrit_S = df.copy()

#%% ---- PROJECTIONS



#%% ---- MODFLOW

#%% CALIBRATION

class MatchingStreams:
    """ 
    
    Class for the calibration based on river occurency
        
    Attributes
    ----------
    
    Methods
    ----------
    
    """

    def __init__(self, 
                 watershed, 
                 iteration_label=None,
                 from_calib=True):
        
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        if from_calib==True:
            self.calibration_folder = watershed.calibration_folder
        else:
            self.calibration_folder = watershed.simulations_folder
        self.iteration_label = iteration_label
        
        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc
              
        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()
        # self.get_indicator()
        
    def prepare_files(self):
        #files are necessary for whiteboxtool
        self.results_folder=os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
        toolbox.create_folder(self.results_folder)
        # New folder results
        self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
        toolbox.create_folder(self.dichotomy_folder)
        
        # Observed buff data
        self.buff_tif_obs = self.hydrography.tif_streams
        # Mask observed
        self.tif_obs = os.path.join(self.dichotomy_folder,'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
        # Obs to points
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        # Trace downslope obs
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
        
        # Mask simulated
        tif_sim = os.path.join(self.results_folder,'_rasters','seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder,'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        # Sim to points
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        # Trace downslope sim
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
        
    def sim_to_obs(self):
        # Simflow to points
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
        self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)   
        
        # Distance of dem to obs
        self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
        
        # Distance of dem to obsflow
        self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)

        # Sim to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
        wbt.add_point_coordinates_to_table(self.pt_simf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
        # Simflow to Obs and Obsflow
        wbt.add_point_coordinates_to_table(self.pt_sim_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
        wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)

    def obs_to_sim(self):
        # Simflow to points
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
        self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)
        
        # Distance of dem to sim
        self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
        # Distance of dem to simflow
        self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
        wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)

        # Obs to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
        wbt.add_point_coordinates_to_table(self.pt_obsf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
        # Obsflow to Sim and Simflow
        wbt.add_point_coordinates_to_table(self.pt_obs_flow)
        wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
        wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
        wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)

#%% PARAMETERS

vers = 'DICHOT2' # dichotomy on 30 catchments (all hydrosystems)
 
box = False # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False
dis_perlen = True
nlay = 1
lay_decay = 1 # 1 for no decay
first_clim = 'mean' # or 'first or value
verti_hk = None # or [ [1e-5, [0, 20]],
verti_sy = None
verti_ss = None
cond_drain = None # or value of conductance
Kmin = 1e-10 * 3600 * 24 
Klog_transf = False
sy = 1 / 100 # -
sy_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
hk_decay = 0
ss = 1e-5
ss_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
bc_left = None # or value
bc_right = None # or value
sea_level = 'None' # or value based on specific data : BV.oceanic.MSL
zone_partic = 'domain' # or watershed
vka = 1
bottom = None
thickness = 50

rec_data = pd.read_csv(rec_path, sep=',')
rec_data = rec_data[['time','rechg']]
rec_mean = rec_data.groupby('time', as_index=False).mean()
rec_mean['time'] = pd.to_datetime(rec_mean['time'])
rec_mean = rec_mean.set_index(['time'])

recharge_csv = rec_mean['rechg']

print(f"Recharge: {recharge_csv.mean()*365} mm/y")

#%% LAUNCH

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

path_dem = BV.geographic.watershed_dem
dem = imageio.imread(path_dem)
dem = np.ma.masked_array(dem, mask=dem<0)
dem_cells = dem.count()

path_buff = BV.geographic.watershed_buff_dem
buff = imageio.imread(path_buff)
buff = np.ma.masked_array(buff, mask=buff<0)
buff_cells = buff.count()

path_box = BV.geographic.watershed_box_buff_dem
boxc = imageio.imread(path_box)
boxc = np.ma.masked_array(boxc, mask=boxc<0)
boxc_cells = boxc.count()

# Create folders
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' # necessary for plots
toolbox.create_folder(simulations_folder)
BV.calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')
toolbox.create_folder(BV.calibration_folder)
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

# Type obs hydro
BV.add_hydrography(data_path, types_obs=['stream_network_urse_reproj'])
        
# Objects
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()
BV.add_oceanic(sea_level)

# Updated
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.climatic.update_first_clim(first_clim)
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_sy(sy)
BV.hydraulic.update_sy_decay(sy_decay)
BV.hydraulic.update_ss(ss)
BV.hydraulic.update_ss_decay(ss_decay)
BV.hydraulic.update_vka(vka)
BV.hydraulic.update_hk_vertical(verti_hk)
BV.hydraulic.update_sy_vertical(verti_sy)
BV.hydraulic.update_ss_vertical(verti_ss)
BV.hydraulic.update_bottom(bottom)
BV.settings.update_dis_perlen(dis_perlen)
BV.settings.update_bc_sides(bc_left, bc_right)
BV.settings.update_input_particles(zone_partic=zone_partic)
BV.hydraulic.update_hk_decay(hk_decay, min_value=Kmin, log_transf=Klog_transf) # 0
BV.hydraulic.update_thick(thickness) # 30 / intervient pas si bottom != None

recharges = [
    ("REF", recharge_dict)
]

for irec, (name, drec) in enumerate(recharges):
    
    df_optim = pd.DataFrame()
    df_calib = pd.DataFrame()
    
    mean_recharge_from_dict = (sum(drec.values()) / len(drec)).mean()
    
    BV.climatic.update_recharge(drec, sim_state=sim_state)
        
    KRmin = 1
    KRmax = 1000

    # Define permeability range
    Kmin = KRmin * mean_recharge_from_dict
    Kmax = KRmax * mean_recharge_from_dict
    
    # Params
    params_df = pd.DataFrame(columns=['params', 'init_values', 'lower_bounds', 'higher_bounds', 'units', 'scale'])
    params_df.loc[0] = ['k1', '?', Kmin, Kmax, 'm/j', 'lin']
    params_file = vers+'_BOUNDS_CALIB_PARAMS'
    params_df.to_csv(BV.calibration_folder+'/'+params_file+'.csv', sep=';', index=None)
    
    p_min = params_df['lower_bounds'].values[0]
    p_max = params_df['higher_bounds'].values[0]
    diff = p_max - p_min
    half = (p_min + p_max) / 2

    gap = 1
    compt = 0
    
    success_modflow = False # init
    
    list_of_model_names = []

    # Main dichotomy loop
    
    valid_result = True
    
    while (diff > ((gap/100) * half)):
                            
        half = (p_min + p_max) / 2
        hyd_cond = half.copy() # if K in calib_params.csv
        kr = hyd_cond / mean_recharge_from_dict
        
        # Update value
        BV.hydraulic.update_hk(hyd_cond)
        
        # Change
        model_name = vers+'_'+\
                     str(name)+'_'+\
                     str(watershed_name)+'_'+str(int(round(area,1)))+'_'+\
                     str(compt)+'_'+\
                     str(round(thickness,1))+'-'+str(int(round(mean_recharge_from_dict*365*1000,1)))+'_'+\
                     str("{:.1e}".format(hyd_cond/24/3600))+'-'+str(int(round(hyd_cond/mean_recharge_from_dict,1))) #+'-'+oclock
                     
        print(model_name)
        BV.settings.update_model_name(model_name)
        
        # Check grid                    
        if compt == 0:
            check_grid = True
        else:
            check_grid = False                        
        BV.settings.update_check_model(plot_cross=plot_cross, check_grid=check_grid)

        # Run
        model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
        
        # Cells
        if compt == 0:
            prob_cells = model_modflow.prob_cells
        
        # Post-process
        BV.postprocessing_modflow(model_modflow,
                                  watertable_elevation = True,
                                  seepage_areas = True,
                                  outflow_drain = True,
                                  accumulation_flux = True,
                                  watertable_depth = True, 
                                  groundwater_flux = True,
                                  groundwater_storage = True,
                                  intermittency_yearly = True,
                                  export_all_tif = False)
        
        iter_results = MatchingStreams(BV, iteration_label=model_name, from_calib=True)
        
        # obs_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
        # obs_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
        # obsf_to_sim = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
        obsf_to_simf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','obsflowf.shp'))
        
        if not os.path.exists(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp')):
            valid_result = False
            break  # Sortie prématurée pour forcer retry ==> not really good
        
        # sim_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
        # sim_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
        # simf_to_obs = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
        simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))
    
        # mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
        # mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
        # mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
        mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])
        
        # mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
        # mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
        # mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
        mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])
                
        ### Conditions
        obs = mean_obsf_to_simf
        sim = mean_simf_to_obsf
        indicator = sim/obs
    
        if sim > obs:
            p_min = half
        if sim < obs:
            p_max = half
        if np.isnan(indicator):
            p_max = half
        
        diff = p_max - p_min
        
        print('==> SIMULATION : '+str(compt))
        print('    K/R = '+str(round(kr, 4)))
        print('    GAP = '+str(round((gap/100) * kr, 4)))
        print('    INDICATOR = '+str(round(indicator, 4)))
                                                
        list_of_model_names.append(BV.calibration_folder+'/'+model_name+'/')
        
        df_calib.loc[compt,'IDX_NODPOL'] = i
        df_calib.loc[compt,'NAME_RECAL'] = watershed_name  
        df_calib.loc[compt,'MODEL_NAME'] = model_name
        df_calib.loc[compt,'COMPT_SIM'] = compt
        df_calib.loc[compt,'INPUT_REC'] = round(mean_recharge_from_dict*1000*365, 4) # mm/y
        df_calib.loc[compt,'AQUI_THICK'] = round(thickness, 4)
        df_calib.loc[compt,'DSO'] = round(sim, 4)
        df_calib.loc[compt,'DOS'] = round(obs, 4)
        df_calib.loc[compt,'DOPTIM'] = round((sim+obs)/2, 4)            
        df_calib.loc[compt,'DSO/DOS'] = round(indicator, 4)
        df_calib.loc[compt,'DSO/DOS_LG'] = round(np.log10(indicator)**2, 10)                    
        df_calib.loc[compt,'K_OPTIM'] = float("{:.5e}".format(hyd_cond/24/3600))                
        df_calib.loc[compt,'K/R_OPTIM'] = round(hyd_cond/mean_recharge_from_dict, 4)
        df_calib.loc[compt,'TMAX_OPTIM'] = df_calib.loc[compt,'K_OPTIM'] * thickness

        compt += 1
        
    if (success_modflow==True) and (os.path.exists(os.path.join(BV.calibration_folder, model_name, '_matchingstreams','simflowf.shp'))):

        # Save ALL
        name_for_save = vers+'_'+str(name)+'_'+str(watershed_name)+'_'+str(round(area,1))
        df_calib.to_csv(BV.calibration_folder+'/'+name_for_save+'_CALIB'+'.csv', sep=';', index=True)
    
        # Save model_modflow
        model_modflow = BV.preprocessing_modflow(for_calib=True) # BV.calibration_folder
        dictio = {}
        dictio['model_modflow'] = model_modflow
        pickle_file = BV.calibration_folder+'/'+model_name+'.pkl'
        with open(pickle_file, 'wb') as f:
            pickle.dump(dictio, f)

        del(dictio)

        timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                          model_modpath=None,
                                                          datetime_format=False,
                                                          subbasin_results=False,
                                                          intermittency_yearly=True) # or None
        
        listfile = os.path.join(BV.calibration_folder, model_name, model_name + '.list')
        
        del(model_modflow)

        sim_series = pd.read_csv(BV.calibration_folder+'/'+model_name+'/'+'_postprocess/_timeseries/_simulated_timeseries.csv', sep=';')
        
        df_optim.loc[0,'IDX_NODPOL'] = i
        df_optim.loc[0,'NAME_RECAL'] = watershed_name
        
        df_optim.loc[0,'MODEL_NAME'] = model_name
        
        df_optim.loc[0,'GRID_RES'] = 75
        df_optim.loc[0,'GRID_BOX'] = boxc_cells
        df_optim.loc[0,'GRID_BUFF'] = buff_cells
        df_optim.loc[0,'GRID_CATCH'] = dem_cells
        df_optim.loc[0,'GRID_CHECK'] = round(prob_cells, 4)
        
        df_optim.loc[0,'COMPT_SIM'] = compt
        
        df_optim.loc[0,'INPUT_REC'] = round(mean_recharge_from_dict*1000*365, 4) # mm/y
        df_optim.loc[0,'AQUI_THICK'] = round(thickness, 4)
    
        df_optim.loc[0,'DSO'] = round(sim, 4)
        df_optim.loc[0,'DOS'] = round(obs, 4)
        df_optim.loc[0,'DOPTIM'] = round((sim+obs)/2, 4)

        df_optim.loc[0,'DSO/DOS'] = round(indicator, 4)
        df_optim.loc[0,'OF_DSO/DOS'] = round(np.log10(indicator)**2, 10)
    
        df_optim.loc[0,'K_OPTIM'] = float("{:.5e}".format(hyd_cond/24/3600))                
        df_optim.loc[0,'K/R_OPTIM'] = round(hyd_cond/mean_recharge_from_dict, 4)
        
        df_optim.loc[0,'WT_ELEV'] = round(sim_series['watertable_elevation'].values[0], 4)
        df_optim.loc[0,'WT_DEPTH'] = round(sim_series['watertable_depth'].values[0], 4)
        
        df_optim.loc[0,'HSAT_OPTIM'] = round(thickness - sim_series['watertable_depth'].values[0], 4) 
        df_optim.loc[0,'HSAT_PROP'] = round((sim_series['watertable_depth'].values[0]/(thickness - sim_series['watertable_depth'].values[0])), 4)
        
        df_optim.loc[0,'TMAX_OPTIM'] = df_optim.loc[0,'K_OPTIM'] * thickness
        df_optim.loc[0,'TSAT_OPTIM'] = df_optim.loc[0,'K_OPTIM'] * df_optim.loc[0,'HSAT_OPTIM']
                    
        df_optim.loc[0,'GW_STORAG'] = round(sim_series['groundwater_storage'].values[0], 4)
        df_optim.loc[0,'GW_FLOW'] = round(sim_series['groundwater_flux'].values[0]/(75*50), 4)
        
        df_optim.loc[0,'DD_SEEP'] = round(sim_series['seepage_areas'].values[0], 4)
        df_optim.loc[0,'DD_NETW'] = round(sim_series['total_areas'].values[0], 4)
        df_optim.loc[0,'DD_RATIO'] = round(sim_series['total_areas'].values[0]/sim_series['seepage_areas'].values[0], 4)
        
        df_optim.loc[0,'OUT_SEEP'] = round(sim_series['outflow_drain'].values[0]*365*1000, 4)
        df_optim.loc[0,'OUT_ACC'] = round((1000*(BV.geographic.area*1e6)*sim_series['outflow_drain'].values[0])/24/60/60, 4)               
        df_optim.loc[0,'OUT_PROP'] = round(df_optim.loc[0,'OUT_SEEP'] / df_optim.loc[0,'INPUT_REC'], 4)
                                                
        df_optim.to_csv(BV.calibration_folder+'/'+name_for_save+'_OPTIM'+'.csv', sep=';', index=True)

    else:
        df_optim.loc[0,:] = np.nan
        df_optim.loc[0,'NAME_RECAL'] = watershed_name
                            
        name_for_save = vers+'_'+str(name)+'_'+str(watershed_name)+'_'+str(round(area,1))
        df_optim.to_csv(BV.calibration_folder+'/'+name_for_save+'_OPTIM'+'.csv', sep=';', index=True)

#%% MAP

BV = watershed_root.Watershed(watershed_name=watershed_name, dem_path=None, out_path=out_path, load=True)
area = BV.geographic.area

stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

model_names = [
    path for path in glob.glob(os.path.join(calibration_folder, vers + '*'))
    if os.path.isdir(path)
]
model_names.sort()
model_name_ref = model_names[-1]

WC0 = os.path.join(stable_folder, 'geographic', 'watershed.shp')
WC_shp = gpd.read_file(WC0)

HYD0 = os.path.join(stable_folder, 'hydrography', 'stream_network_urse_reproj.shp')
HYD_shp = gpd.read_file(HYD0)

for i, model_path in enumerate([model_name_ref]):
    
    stable_folder = os.path.join(out_path, watershed_name, 'results_stable') # necessary for plots
    simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')
    calibration_folder = os.path.join(out_path, watershed_name, 'results_calibration')

    simflowf_path = os.path.join(model_path, '_matchingstreams', 'simflowf.shp')
    simflowf = gpd.read_file(simflowf_path)
    
    fig, ax = plt.subplots(1,1, figsize=(10,10), dpi=300)
    
    simflowf.plot(ax=ax, column='VALUE1', cmap='RdYlGn_r', lw=0, zorder=1, s=50,
                  marker='s',
                  vmin=0,vmax=25*10)
    
    HYD_shp.plot(ax=ax, color='blue', lw=4, zorder=0)
    
    WC_shp.plot(ax=ax, facecolor='None', zorder=2, lw=4)
    
    plt.suptitle(os.path.basename(model_path), fontsize=10, y=1)
    
    plt.tight_layout()
    
#%% ---- NOTES

os.chdir(DIR)
