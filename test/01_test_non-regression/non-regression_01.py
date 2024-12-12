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

# PYTHON PACKAGES

import sys
import os
import warnings

import numpy as np
import pandas as pd
import flopy
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')
import imageio
import whitebox
import rasterio
import geopandas as gpd
from mpl_toolkits.axes_grid1 import make_axes_locatable
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# ROOT DIRECTORY

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

# HYDROMODPY MODULES

#import src
import importlib
#importlib.reload(src)
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

# WARNING MANAGEMENT

warnings.filterwarnings("ignore")
    
#%% ---- PERSONAL PATHS

regression_path = os.path.join(root_dir, "test", "01_test_non-regression/")
data_path = os.path.join(regression_path, "data/")

# The folder out_path is created in the example_path root directory:
out_path = os.path.join(root_dir, "test", "results")
# Or use a function to update the root folder
# out_path = folder_root.update_root_folder_results()
# Or define it manually
# out_path = 'C:/Simulations/HydroModPy/'

print('The results of the example will be saved here :', out_path)

#%% ---- EXTRACT CATCHMENT

# Name of the study site
watershed_name = 'Regression_01_Aber'
print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dem_path = os.path.join(data_path, 'regional dem.tif')

# Outlet coordinates of the catchment
from_xyv = [150727.164, 6858066.520, 100, 10 , 'EPSG:2154']

# Extract the catchment from a regional DEM
BV = watershed_root.Watershed(dem_path=dem_path,
                              out_path=out_path,
                              load=False,
                              watershed_name=watershed_name,
                              from_lib=None, # os.path.join(root_dir,'watershed_library.csv')
                              from_dem=None, # [path, cell size]
                              from_shp=None, # [path, buffer size]
                              from_xyv=from_xyv, # [x, y, snap distance, buffer size]
                              bottom_path=None, # path 
                              save_object=True)

# Paths necessary for the script
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% ---- ADD DATA

# Clip specific data at the catchment scale
BV.add_hydrography(data_path, types_obs=['regional stream network'])

#%% ---- MODEL PARAMETRIZATION

# Name of the model/simulation
model_name = 'reg_0'

# Import modules
BV.add_settings()
BV.add_climatic()
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name) # Name of the model/simulation
BV.settings.update_box_model(True)
BV.settings.update_sink_fill(False)
BV.settings.update_simulation_state('steady') # Transient
BV.settings.update_active_plot(plot_cross=False)
BV.settings.update_split_temporal(split_temp=False)

# Climatic settings
BV.climatic.update_recharge(100 / 1000 / 365, sim_state=BV.settings.sim_state)
BV.climatic.update_first_clim('mean') # or 'first or value

# Hydraulic settings
BV.hydraulic.update_nlay(1)
BV.hydraulic.update_lay_decay(1) # 1 if not activated
BV.hydraulic.update_bottom(None) # Set a value to set a flat bottom
BV.hydraulic.update_thick(50) # Not consider if bottom != of None
BV.hydraulic.update_hyd_cond(1e-5 * 24 * 3600) # m/d
BV.hydraulic.update_porosity(1/100) # -
BV.hydraulic.update_cond_decay(0) # Exponential decay with depth : 1/10 (about half decrease at 10m)
BV.hydraulic.update_poro_decay(0)
BV.hydraulic.update_cond_vertical(None) # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
BV.hydraulic.update_cond_drain(None)

# Boundary settings
BV.settings.update_bc_sides(None, None)
BV.add_oceanic('None')

# Particle tracking settings
BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem)

#%% ---- GROUNDWATER FLOW MODEL RUN

# Pre-processing
model_modflow = BV.preprocessing_modflow(for_calib=False)

# Processing
success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

# Post-processing
if success_modflow == True:
    BV.postprocessing_modflow(model_modflow,
                              watertable_elevation=True,
                              watertable_depth=True, 
                              seepage_areas=True,
                              outflow_drain=True,
                              groundwater_flux=True,
                              groundwater_storage=True,
                              accumulation_flux=True,
                              persistency_index=False, # only in transient
                              intermittency_monthly=False, # only in transient
                              intermittency_weekly=False, # only in transient
                              intermittency_daily=False, # only in transient
                              export_all_tif=False)

#%% ---- PARTICLE TRACKING RUN

# Pre-processing
if success_modflow == True:
    model_modpath = BV.preprocessing_modpath(model_modflow)

# Processing
    success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

# Post-processing
if success_modpath == True:
    BV.postprocessing_modpath(model_modpath,
                              ending_point=True,
                              starting_point=False,
                              pathlines_shp=False,
                              particles_shp=False,
                              random_id=None) # None
    
    BV.filtprocessing_modpath(model_modpath,
                              norm_flux=True, # for forward only
                              filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                              filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                              filt_inout=True, # delete particles in and out in the same cell (first layer)
                              calc_rtd=True, # compute residence time distribution
                              random_id=None, # select randomly to keep
                              ) # None

#%% ---- GENERATE TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=False, 
                                                  subbasin_results=True,
                                                  freq_time='D') # or 'M' or None

#%% ---- PLOT QUICK VIEW RESULTS

print('Plot quick view 2D visulization')

shp = gpd.read_file(BV.stable_folder+'/geographic/watershed.shp')
wt_rio = rasterio.open(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/watertable_depth_t(0).tif')
wt_data = wt_rio.read(1)
# seep_rio = rasterio.open(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/seepage_areas_t(0).tif')
# seep_data = np.ma.masked_where(seep_rio.read(1)<=0, seep_rio.read(1))

fig, ax = plt.subplots(1,1, figsize=(7, 5))
retted = rasterio.plot.show(wt_data, ax=ax, transform=wt_rio.transform, cmap='RdBu', alpha=0.7, zorder=0, aspect="auto")
# rasterio.plot.show(seep_data, ax=ax, transform=seep_rio.transform, cmap=mpl.colors.ListedColormap(['darkorange']), alpha=1, zorder=1, aspect="auto")
shp.plot(ax=ax, lw=2, ec='k', fc='None')
ax.set_title('Water table [m]')
im = retted.get_images()[0]
divider = make_axes_locatable(ax)
cax = divider.append_axes('right', size='5%', pad=0.5)
fig.colorbar(im, cax=cax)
fig.tight_layout()

#%% ---- NON-REGRESSION TEST

reference_wt = imageio.imread(regression_path+'/reference/'+'watertable_depth_t(0).tif')
simulated_wt = imageio.imread(BV.simulations_folder+'/'+model_name+'/_postprocess/_rasters/watertable_depth_t(0).tif')

if (reference_wt==simulated_wt).all():
    print('VALIDATED: NON REGRESSION TEST ON WATERTABLE DEPTH')
else:
    print('NO VALIDATED: NON REGRESSION TEST ON WATERTABLE DEPTH')

reference_csv = pd.read_csv(regression_path+'/reference/'+'_simulated_timeseries.csv', sep=';')
simulated_csv = pd.read_csv(BV.simulations_folder+'/'+model_name+'/_postprocess/_timeseries/_simulated_timeseries.csv', sep=';')

if reference_csv.equals(simulated_csv) == True:
    print('VALIDATED: NON REGRESSION TEST VALIDATED ON TIME SERIES')
else:
    print('NO VALIDATED: NON REGRESSION TEST ON TIME SERIES')

#%% ---- PLOT COMPLETE RESULTS

# print('Plot complete 2D visulization')

# visu = visualization_results.Visualization(BV, model_name)
# visu.visual2D(object_list = [
#                              'map',
#                              'grid',
#                              'watertable',
#                              'watertable_depth',
#                              'drain_flow',
#                              'surface_flow',
#                              'pathlines',
#                              'residence_times'
#                              ],
#               color_scale = [
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              (None,None),
#                              ], 
#                              lines=None)

#%% ---- NOTES

os.chdir(root_dir)
