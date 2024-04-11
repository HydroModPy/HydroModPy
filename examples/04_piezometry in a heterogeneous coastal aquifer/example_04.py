# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Martin Le Mesnil, Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

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
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from mpl_toolkits.axes_grid1 import make_axes_locatable
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'inline')

# Libraries added from 'conda forge' procedure

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
from src.tools import toolbox, folder_root

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

example_path = root_dir + "/examples/04_piezometry in a heterogeneous coastal aquifer/"
data_path = os.path.join(example_path, "data") + '/'
out_path = folder_root.update_root_folder_results()
# To change the folder path: out_path = folder_root.update_root_folder_results()
# To search folder path: out_path = folder_root.root_folder_results()

#%% ---- WATERSHED

#%% OPTIONS

dem_path = data_path + "MNT_gouville_25m.tif"
oceanic_path = data_path + 'oceanic/'
recharge_path = data_path + 'recharge/_REC_D.csv'
shape_calib_zones_path = os.path.join(data_path, 'shapefile', 'param_zones.shp')

load = False
watershed_name = 'Gouville'
from_lib = None # os.path.join(root_dir,'watershed_library.csv')
from_dem = None # [path, cell size]
from_shp = [data_path + 'shapefile/model_area.shp', 10] # [path, buffer size]
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
                              # modflow_path=modflow_path, 
                              save_object=save_object)

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

#%% ---- DATA

#%% INIT

# Clip specific data at the catchment scale
BV.add_piezometry()
BV.add_oceanic(oceanic_path)

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
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

filename = 'piezometry_' + str.replace(code, '/', '') + '_363782_6897114_9.2_10' + '.csv' #check if needed
piezo_add_path = os.path.join(stable_folder, 'add_data',  filename)
if not os.path.exists(os.path.join(stable_folder, 'add_data')):
    os.mkdir(os.path.join(stable_folder, 'add_data'))
piezo_NGF_df.to_csv(piezo_add_path, sep = ';',)

BV.piezometry.add_data()
BV.piezometry.display_data()

#%% RECHARGE

first_clim = 'mean'
freq_time = 'D'

BV.add_climatic()
BV.climatic.update_first_clim(first_clim)

BV.climatic.update_recharge_reanalysis(path_file = recharge_path,
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
ax.plot(sl, label='sea_level', c='navy', lw=2)
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

# Hydraulic settings
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = -20 # elevation in meters, None for constant aquifer thickness, or 2D matrix
thick = None # if bottom is None, aquifer thickness
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

# Lateral heterogeneity of hydrodynamic parameters
hyd_cond_1 = 18.5 # m/day
hyd_cond_2 = 95 # m/day
porosity_1 = 8 / 100 # -
porosity_2 = 45 / 100 # -

# Boundary settings
bc_left = None # or value
bc_right = None # or value

#%% UPDATE

# Import modules
BV.add_settings()
BV.add_geometric() # soon
BV.add_hydraulic()

# Frame settings
BV.settings.update_model_name(model_name)
BV.settings.update_box_model(box)
BV.settings.update_sink_fill(sink_fill)
BV.settings.update_simulation_state(sim_state)
BV.settings.update_active_plot(plot_cross=plot_cross)

# Hydraulic settings
BV.hydraulic.update_nlay(nlay) # 1
BV.hydraulic.update_lay_decay(lay_decay) # 1
BV.hydraulic.update_bottom(bottom) # None
BV.hydraulic.update_thick(thick) # 30 / intervient pas si bottom != None
# BV.hydraulic.update_hyd_cond(hyd_cond)
# BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Lateral heterogeneity
BV.hydraulic.update_calib_zones_from_shp(shape_calib_zones_path)
BV.hydraulic.update_hyd_cond_from_calib_zones(1, hyd_cond_1)
BV.hydraulic.update_hyd_cond_from_calib_zones(2, hyd_cond_2)
BV.hydraulic.update_porosity_from_calib_zones(1, porosity_1)
BV.hydraulic.update_porosity_from_calib_zones(2, porosity_2)

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
                              export_all_tif = False,
                              export_netcdf = True)
    timeseries_results = BV.postprocessing_timeseries(model_modflow=model_modflow,
                                                      model_modpath=None,
                                                      actual_date=True, 
                                                      subbasin_results=False,
                                                      freq_time=freq_time)

#%% SIMULATED VS OBSERVED PIEZOMETRY

dem_data = BV.geographic.dem_clip

watertable_elevation = np.load(os.path.join(simulations_folder, 'default',
                                            '_postprocess', 'watertable_elevation.npy'),
                               allow_pickle=True).item()

sim_piezo_elev = []
for t in range(len(watertable_elevation)):
    sim_piezo_elev.append(watertable_elevation[t][BV.piezometry.x_iloc,BV.piezometry.y_iloc][0])
df_simobs_piezo_elev = piezo_2016.copy()
df_simobs_piezo_elev.insert(1, "Sim", sim_piezo_elev)

watertable_depth = np.load(os.path.join(simulations_folder, 'default',
                                            '_postprocess', 'watertable_depth.npy'),
                               allow_pickle=True).item()
sim_piezo_depth = []
for t in range(len(watertable_depth)):
    sim_piezo_depth.append(watertable_depth[t][BV.piezometry.x_iloc,BV.piezometry.y_iloc][0])
df_simobs_piezo_depth = piezo_2016.copy()
df_simobs_piezo_depth.insert(1, "Sim", sim_piezo_depth)

fig, ax = plt.subplots(1,1, figsize=(8,6), sharex=True)
ax.plot(df_simobs_piezo_elev.NGF, label='Observed', color='k', lw=2)
ax.plot(df_simobs_piezo_elev.Sim, label='Simulated', color='red', lw=2)
ax.legend(loc='best', fontsize=10)
ax.set_ylabel('Elevation [m a.s.l.]')
ax.set_title('Watertable')

# fig, axs = plt.subplots(2,1, figsize=(8,6), sharex=True)
# axs = axs.ravel()

# ax = axs[0]
# ax.plot(df_simobs_piezo_elev.NGF, label='Observed', color='k', lw=2)
# ax.plot(df_simobs_piezo_elev.Sim, label='Simulated', color='red', lw=2)
# years_maj = mdates.YearLocator()   # every year
# months_maj = mdates.MonthLocator()  # every x month
# ax.xaxis.set_major_locator(years_maj)
# ax.xaxis.set_minor_locator(months_maj)
# ax.legend(loc='upper right', fontsize=8)
# ax.set_ylabel('Elevation [m]')
# ax.set_xlim(pd.to_datetime('2016-01'), pd.to_datetime('2017-01'))
# ax.set_title('Watertable')

# ax = axs[1]
# ax.axhline(dem_data[30,30], label='Topography', color='brown', lw=2)
# ax.plot(dem_data[30,30]-df_simobs_piezo_depth.NGF, label='Observed', color='k', lw=2)
# ax.plot(df_simobs_piezo_depth.Sim, label='Simulated', color='red', lw=2)
# years_maj = mdates.YearLocator()   # every year
# months_maj = mdates.MonthLocator()  # every x month
# ax.xaxis.set_major_locator(years_maj)
# ax.xaxis.set_minor_locator(months_maj)
# ax.legend(loc='upper right', fontsize=8)
# ax.set_ylabel('Depth [m]')
# ax.set_xlim(pd.to_datetime('2016-01'), pd.to_datetime('2017-01'))

# fig, ax = plt.subplots(1,1, figsize=(10,3))
# watertable_depth[0][watertable_depth[0]<0] = 0
# im = ax.imshow(watertable_depth[0], cmap='RdYlBu_r')
# ax.set_xlabel('Cells on X', fontsize=10)
# ax.set_ylabel('Cells on Y', fontsize=10)
# ax.set_title('Study site  -  Watertable depth [m]  -  First time step', fontsize=15)
# ax_divider = make_axes_locatable(ax)
# cax = ax_divider.append_axes("right", size="2%", pad="2%")
# cb = fig.colorbar(im, cax=cax)
# cb.set_ticks([0,5,10,15])

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
                                  particules_shp=True,
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
                                                  actual_date=True, 
                                                  subbasin_results=subbasin_results,
                                                  freq_time=freq_time) # or None

#%% 2D PLOT

# # if sim_state == 'steady':
# visu = visualization_results.Visualization(BV, model_name)
# visu.visual2D(object_list = ['map','grid',
#                               'watertable', 'watertable_depth',
#                               'drain_flow','surface_flow',
#                               'pathlines', 'residence_times'
#                               ],
#               color_scale = [(None,None),(None,None),
#                               (None,None),(0,10),
#                               (None,None),(None,None),
#                               (None,None),(None,None),
#                               ], 
#               lines=250)

#%% ---- NOTES
