# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Martin Le Mesnil, Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

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

#%% PERSONAL PATHS

example_path = root_dir + "/examples/04_piezometry in a coastal context/"
data_path = example_path + "data/"
out_path = r'C:\Users\Martin Le Mesnil\Travail\HydroModPy\output_01'

#%% ---- WATERSHED

#%% OPTIONS

dem_path = data_path + "regional_dem.tif"
oceanic_path = data_path + 'oceanic/'
recharge_path = data_path + 'recharge/_REC_D.csv'
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

# Clip specific data at the catchment scale
BV.add_piezometry()
BV.add_oceanic(oceanic_path)

# General plot of the study site
visualization_watershed.watershed_local(dem_path, BV)
visualization_watershed.watershed_dem(BV)

#%% RECHARGE and SEA data

first_clim = 'mean'
BV.add_climatic()
BV.climatic.update_first_clim(first_clim)

BV.climatic.update_recharge_reanalysis(path_file = recharge_path,
                                       clim_mod='REA',
                                       clim_sce='historic',
                                       first_year=2016,
                                       last_year=2016,
                                       time_step='D',
                                       sim_state='transient')
BV.climatic.update_first_clim(first_clim)
rec = BV.climatic.recharge
plt.plot(rec)

sea_lev = pd.read_csv(data_path + 'sea_level.csv', header=None)
sea_level = sea_lev[1].values.tolist()
BV.oceanic.update_MSL(sea_level)
# sl = BV.oceanic.MSL
# plt.plot(sl)

#%% ---- PARAMETRIZATION

#%% DEFINE

# Frame settings
model_name = 'default'
box = True # or False
sink_fill = False # or True
sim_state = 'transient' # 'steady' or 'transient'
plot_cross = True

# Hydraulic settings
nlay = 1
lay_decay = 1 # 1 for no decay
bottom = -20 # elevation in meters, None for constant aquifer thickness, or 2D matrix
thick = None # if bottom is None, aquifer thickness
hyd_cond = 20 # m/day
cond_decay = 0 # exponential decay : 1/20 (half decrease at 20m)
verti_cond = None # or [ [1e-5, [0, 20]], [1e-6, [20,80]] ]
cond_drain = None # or value of conductance
porosity = 10 / 100 # -
poro_decay = 0 # exponential decay : 1/20 (half decrease at 20m)

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
BV.hydraulic.update_hyd_cond(hyd_cond)
BV.hydraulic.update_porosity(porosity)
BV.hydraulic.update_cond_vertical(verti_cond)
BV.hydraulic.update_cond_drain(cond_drain)
BV.hydraulic.update_lay_decay(poro_decay)

# Boundary settings
BV.settings.update_bc_sides(bc_left, bc_right)


#%% ---- MODELING

#%% MODFLOW

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
                                                  subbasin_results=subbasin_results) # or None

#%% ---- PLOT

#%% 2D

# if sim_state == 'steady':
visu = visualization_results.Visualization(BV, model_name)
visu.visual2D(object_list = ['map','grid',
                             'watertable', 'watertable_depth',
                             'drain_flow','surface_flow',
                             'pathlines', 'residence_times'
                             ],
              color_scale = [(None,None),(None,None),
                             (None,None),(0,10),
                             (None,None),(None,None),
                             (None,None),(None,None),
                             ], 
              lines=100)

#%% 3D

if from_dem == None:
    export_vtuvtk.VTK(BV, model_name)
    visu = visualization_results.Visualization(BV, model_name)
    visu.visual3D(interactive=True,
                  object_list=['grid','watertable', 'watertable_depth',
                               'surface_flow', 'drain_flow', 'pathlines'
                               ],
                  view='south-west',
                  lines=100, cloc=(0.7,0.1))

#%% RAW

lead_numb = '0'
outflow = imageio.imread(simulations_folder+model_name+'/_postprocess/_rasters/accumulation_flux_t(0).tif')
demData = imageio.imread(BV.geographic.watershed_dem)
demData = np.ma.masked_array(demData, mask=demData<0)
res = BV.geographic.resolution

msk_outflow = (outflow<0)
outflow = np.ma.masked_array(outflow, mask=msk_outflow)
outflow = ( np.ma.masked_where(outflow==0, outflow) / (res**2) )
outflow = outflow * 1000 * 365 # mm/year
outflow = np.log10(outflow)

from matplotlib.colors import LightSource
ls = LightSource(azdeg=45, altdeg=45)
cmap = plt.cm.Greys
rgb = ls.shade(demData, cmap=cmap, blend_mode='soft', vert_exag=2, dx=res, dy=res)

fig, ax = plt.subplots(1, 1, figsize=(6,6), dpi=300)
ax.get_xaxis().set_visible(False)
ax.get_yaxis().set_visible(False)
im = ax.imshow(demData, alpha=0.8, cmap=cmap)
im = ax.imshow(rgb, alpha=0.8, cmap=cmap)
cf=ax.imshow(outflow, cmap='jet', alpha=1, vmin=outflow.min(), vmax=outflow.max())
try:
    cont = imageio.imread(BV.geographic.watershed_contour_tif)
    ax.imshow(np.ma.masked_where(cont<0, cont), cmap=mpl.colors.ListedColormap(['k']))
except:
    pass

divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="1%", pad=0.05)
fig.add_axes(cax)
cbar = fig.colorbar(im, cax=cax, orientation="vertical")
val = np.ma.masked_where(demData < 0, demData)
minVal =  int(round(np.nanmin(val[np.nonzero(val)],0)))
maxVal =  int(round(np.nanmax(val[np.nonzero(val)],0)))
meanVal = int(round(minVal+((maxVal-minVal)/2),0))
cbar.set_ticks([minVal, meanVal, maxVal])
cbar.set_ticklabels([minVal, meanVal, maxVal])
cbar.mappable.set_clim(minVal, maxVal)
cbar.ax.tick_params(labelsize=10)

cax = divider.new_vertical(size="2%", pad=0.05, pack_start=True)
fig.add_axes(cax)
cbar = fig.colorbar(cf, cax=cax, orientation="horizontal")
ticks = np.linspace(0, outflow.max(), 5)
cbar.set_ticks(ticks)
cbar.set_ticklabels(ticks.round(1))
cbar.set_label('Seepage outflow log [mm/y]')

plt.tight_layout()
name_fig = 'map_discharge_' + str(lead_numb) + '.png'
plt.tight_layout()

fig.savefig(os.path.join(simulations_folder, model_name,
                            '_postprocess', '_figures', 'RAW_'+model_name+'.png'))

#%% CROSS

dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif') # dem data
if from_dem == None:
    stream_data = imageio.imread(stable_folder+'/hydrography/'+'regional stream network.tif') # river data
else:
    stream_data = None
watertable_data = imageio.imread(simulations_folder+model_name+'/_postprocess/_rasters/'+'watertable_elevation_t(0).tif') # watertable data
interactive = True
visu = visualization_results.Visualization(BV, model_name)
visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

#%% ---- NOTES

os.chdir(root_dir)
