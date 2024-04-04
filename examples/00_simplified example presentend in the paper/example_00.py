# -*- coding: utf-8 -*-
"""

Created on 2023.

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

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

import matplotlib as mpl
import matplotlib.pyplot as plt
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

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

print("Root path directory is: {0}".format(root_dir.upper()))

#%% HYDROMODPY

import src
import importlib
importlib.reload(src)

# Import HydroModPy modules
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% PERSONAL

example_path = os.path.join(root_dir, 
                            r"examples/00_simplified example presentend in the paper")
data_path = os.path.join(example_path, "data")
out_path = folder_root.root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()

#%% ---- WATERSHED

#%% OPTIONS

dem_path = os.path.join(data_path, 'regional dem.tif')
watershed_name = 'Example'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = None # [path, buffer size]
from_xyv = [327816.965, 6777886.670, 150, 10 , 'EPSG:2154'] # [x, y, snap distance, buffer size, crs proj]
bottom_path = None # path
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
stable_folder = os.path.join(out_path, watershed_name, 'results_stable')
simulations_folder = os.path.join(out_path, watershed_name, 'results_simulations')

#%% DATA

# Clip specific data at the catchment scale
BV.add_geology(data_path, types_obs='GEO1M.shp', fields_obs='CODE_LEG')
BV.add_hydrography(data_path, types_obs=['regional stream network'])
BV.add_hydrometry(data_path, 'france hydrometric stations.shp')
BV.add_intermittency(data_path, 'regional onde stations.shp')

# Extract some subbasin from data available above
BV.add_subbasin(os.path.join(data_path, 'additional'), 150)

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_geology(BV)
visualization_watershed.watershed_dem(BV)

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'test'
box = True # or False
sink_fill = False # or True
sim_state = 'steady' # 'steady' or 'transient'
plot_cross = False

# Climatic settings
recharge_year = 350 # mm/year
recharge_day = recharge_year / 365 / 1000 #♠ m/day
BV.add_climatic()
first_clim = 'mean' # or 'first or value
freq_time = 'D'

# Hydraulic settings
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = None # elevation in meters, None for constant auifer thickness, or 2D matrix
thick = 30 # if bottom is None, aquifer thickness
hyd_cond = 2e-5 * 24 * 3600 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 1 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

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
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Climatic settings
BV.climatic.update_recharge(recharge_day, sim_state=sim_state)
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

#%% ---- MODELING

#%% MODFLOW

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
                              accumulation_flux = True,
                              persistency_index=False,
                              intermittency_monthly=False,
                              intermittency_daily=False,
                              export_all_tif = False,
                              export_netcdf = False)

#%% MODPATH

if success_modflow == True:
    model_modpath = BV.preprocessing_modpath(model_modflow)
    success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)
if success_modpath == True:
    BV.postprocessing_modpath(model_modpath,
                              ending_point=True,
                              starting_point=True,
                              pathlines_shp=True,
                              particules_shp=False,
                              random_id=None) # None

#%% TIMESERIES

timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                  model_modpath=model_modpath,
                                                  actual_date=True, 
                                                  subbasin_results=True,
                                                  freq_time=freq_time) # or None

#%% ---- PLOT

#%% 2D

# if sim_state == 'steady':
visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                             'watertable', 'watertable_depth',
                             'drain_flow','surface_flow',
                             'pathlines', 'residence_times'
                             ],
              color_scale = [(None,None),(50,140),
                             (50,140),(0,10),
                             (0,300),(0,30000),
                             (0,2.5),(0,5),
                             ], 
                              lines=750)

#%% ---- NOTES

os.chdir(root_dir)
