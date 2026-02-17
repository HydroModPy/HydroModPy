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
# Libraries installed by default
import sys
import os

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mpl_toolkits.axes_grid1 import make_axes_locatable

# Libraries added from 'conda forge' procedure

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

try:
    import hydromodpy
except:
    pass

# ROOT DIRECTORY
from os.path import dirname, abspath
try:
    root_dir = dirname(dirname(dirname(abspath(__file__))))
except NameError:
    root_dir = os.getcwd()
sys.path.append(root_dir)

# HYDROMODPY MODULES
from hydromodpy import watershed_root
from hydromodpy.display import visualization_watershed, visualization_results
from hydromodpy.tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20)  # small, medium, interm, large

#%% PERSONAL PATHS

example_path = os.path.join(root_dir, "examples", "05S_short/")
data_path = os.path.join(example_path, "data/")

# The folder out_path is created in the example_path root directory:
out_path = os.path.join(root_dir,'examples', 'results')
# Or define it manually
# out_path = 'C:/Simulations/HydroModPy/'

print('The results of the example will be saved here :', out_path)

#%% ---- WATERSHED

#%% OPTIONS

dem_path = data_path + "MNT_gouville_75m.tif"

watershed_name = '05S_short'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = [data_path + 'model_area.shp', 10] # [path, buffer size]
from_xyv = None # [x, y, snap distance, buffer size]
bottom_path = None # path
modflow_path = os.path.join(root_dir,'bin/')
save_object = True

#%% GEOGRAPHIC

print('##### '+watershed_name.upper()+' #####')

load = True
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
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% ---- DATA

#%% INIT

visualization_watershed.watershed_local(dem_path, BV)

# Clip specific data at the catchment scale
oceanic_path = data_path
BV.add_oceanic(oceanic_path) # import specific data of tide temporal dynamcis
# BV.add_piezometry() # download data on the web

# General plot of the study site
visualization_watershed.watershed_dem(BV)

#%% PIEZOMETRY

code = '01423X0044/F4' #BSS piezometer code

file = os.path.join(data_path, 'piezo.txt')
df = pd.read_csv(file, delimiter = '|',header=0, engine='python', encoding='latin1')
piezo_NGF_df = df[['Date de la mesure','Côte NGF']]
piezo_NGF_df.columns = ['Date', 'NGF']
piezo_2016 = piezo_NGF_df.copy()
piezo_NGF_df.index = piezo_NGF_df['Date']
piezo_NGF_df = piezo_NGF_df.drop(['Date'], axis=1)
piezo_NGF_df.columns = [code]

piezo_2016.index = pd.to_datetime(piezo_2016['Date'],format='%d/%m/%Y %H:%M:%S')
piezo_2016 = piezo_2016.drop(['Date'], axis=1)
piezo_2016 = piezo_2016[piezo_2016.index.year == 2016]
piezo_2016 = piezo_2016.resample('M').mean()

filename = 'piezometry_' + str.replace(code, '/', '') + '_363782_6897114_9.2_10' + '.csv' #check if needed
piezo_add_path = os.path.join(stable_folder, 'add_data',  filename)
if not os.path.exists(os.path.join(stable_folder, 'add_data')):
    os.mkdir(os.path.join(stable_folder, 'add_data'))
piezo_NGF_df.to_csv(piezo_add_path, sep = ';',)

# BV.piezometry.add_data()
# BV.piezometry.display_data()

#%% RECHARGE

first_clim = 'mean'
freq_time = 'M'

BV.add_climatic()
BV.climatic.update_first_clim(first_clim)

BV.climatic.update_recharge_reanalysis(path_file = data_path + '_REC_D.csv',
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=2016,
                                       last_year=2016,
                                       time_step=freq_time,
                                       sim_state='transient')
BV.climatic.update_first_clim(first_clim)
rec = BV.climatic.recharge

fig, ax = plt.subplots(1,1, figsize=(7,4))
ax.plot(rec, label='recharge_reanalysis', c='dodgerblue', lw=2)
ax.set_xlabel('Date')
ax.set_ylabel('Recharge [mm/d]')
plt.xticks(rotation=45, ha="right")
ax.legend()

BV.climatic.update_recharge(rec/1000, sim_state='transient')

#%% SEA LEVEL

sea_lev = pd.read_csv(data_path + 'sea_level.csv', header=None)
sea_level = sea_lev[1].values.tolist()
BV.oceanic.update_MSL(sea_level)
sl = BV.oceanic.MSL

fig, ax = plt.subplots(1,1, figsize=(7,4))
ax.plot(sl, c='navy', lw=2, label='Sea level')
ax.set_xlabel('Days')
ax.set_ylabel('Sea level [m.a.s.l]')
plt.xticks(rotation=45, ha="right")
ax.legend()

# Since initial state of transient-state simulation is obtained
# using a permanent-state simulation based on t0 values,
# sea level at t0 is set to its mean value.
sea_level[0] = np.mean(sea_level)
BV.oceanic.update_MSL(sea_level)

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = False # or True
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True
dis_perlen = False

# Hydraulic settings
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = -20 # elevation in meters, None for constant aquifer thickness, or 2D matrix
thick = None # if bottom is None, aquifer thickness
cond_drain = None # or value of conductance

# Lateral heterogeneity of hydrodynamic parameters
hk_1 = 18.5 # m/day
hk_2 = 95 # m/day
sy_1 = 8 / 100 # -
sy_2 = 45 / 100 # -

# Boundary settings
bc_left = None # or value
bc_right = None # or value

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_check_model(plot_cross=plot_cross)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
BV.hydraulic.update_cond_drain(cond_drain)
BV.settings.update_dis_perlen(dis_perlen=dis_perlen)

# Lateral heterogeneity
shape_calib_zones_path = os.path.join(data_path, 'param_zones.shp')
BV.hydraulic.update_calib_zones_from_shp(shape_calib_zones_path)
calib_zones = BV.hydraulic.calib_zones
BV.hydraulic.update_hk_from_calib_zones(1, hk_1)
BV.hydraulic.update_hk_from_calib_zones(2, hk_2)
BV.hydraulic.update_sy_from_calib_zones(1, sy_1)
BV.hydraulic.update_sy_from_calib_zones(2, sy_2)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)

#%% ---- MODELING

#%% MODFLOW

# BV.climatic.update_first_clim('first')

model_modflow = BV.preprocessing_modflow(for_calib=False)
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation = True,
                              watertable_depth= True,
                              seepage_areas = True,
                              outflow_drain = True,
                              groundwater_flux = True,
                              groundwater_storage = True,
                              accumulation_flux = False,
                              persistency_index=False,
                              intermittency_monthly=False,
                              intermittency_daily=False,
                              export_all_tif = False)
    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=None,
                                                      datetime_format=True,
                                                      subbasin_results=False)
    netcdf_results = BV.postprocessing_netcdf(model_modflow,
                                              datetime_format=True)

#%% SIMULATED VS OBSERVED PIEZOMETRY

dem_data = BV.geographic.dem_clip

watertable_elevation = np.load(os.path.join(simulations_folder, 'default',
                                            '_postprocess', 'watertable_elevation.npy'),
                               allow_pickle=True).item()

watertable_depth = np.load(os.path.join(simulations_folder, 'default',
                                            '_postprocess', 'watertable_depth.npy'),
                               allow_pickle=True).item()

fig, ax = plt.subplots(1,1, figsize=(10,3))
watertable_depth[0][watertable_depth[0]<0] = 0
im = ax.imshow(watertable_depth[0], cmap='RdYlBu_r')
ax.set_xlabel('Cells on X', fontsize=10)
ax.set_ylabel('Cells on Y', fontsize=10)
ax.set_title('Study site  -  Watertable depth [m]  -  First time step', fontsize=15)
ax_divider = make_axes_locatable(ax)
cax = ax_divider.append_axes("right", size="2%", pad="2%")
cb = fig.colorbar(im, cax=cax)
cb.set_ticks([0,5,10,15])

#%% MODPATH

if sim_state == 'steady':
    if success_modflow == True:
        model_modpath = BV.preprocessing_modpath(model_modflow)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
    if success_modpath == True:
        BV.postprocessing_modpath(model_modpath,
                                  ending_point=True,
                                  starting_point=True,
                                  pathlines_shp=True,
                                  particles_shp=True,
                                  random_id=100)

#%% TIMESERIES

if from_dem == None:
    subbasin_results = True
else:
    subbasin_results = False

if sim_state == 'steady':
    model_modpath = model_modpath
else:
    model_modpath = None

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  datetime_format=True,
                                                  subbasin_results=subbasin_results) # or None

#%% ---- NOTES
