# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

#%% GENERAL LIBRARIES

# General
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
from glob import glob
import numpy as np
import pandas as pd
from osgeo import gdal, osr
# Plot
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import matplotlib as mpl
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator
# Gis
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = True
# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
import random
                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, forcing
from tools import tif_adds, serie_transf, tif_features, file_adds, to_plot, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import plots

#%% LAYOUT PLOT

fontprop = to_plot.plot_params(8,15,18,20) # small, medium, interm, large

#%% NECESSARY PATHS

# Path to the git repositoty home page
git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the test folder
test_path = git_path + "examples/_example/"
# Path where the results will be stored
out_path = "D:/Users/abherve/TEST/"

# We suggest to store the data in specific folder
dems_path = test_path + 'dem/'
hydrology_path = test_path + 'hydrology/' # add hydrographic shapefiles
modflow_path = test_path + 'modflow/' # add bin/ folder with necessary .exe
climate_path =test_path + 'climate/'

piezometry_path = None # add piezometry data or nothing for automatic download
geology_path = None # add geologic layers
oceanic_path = None # add specific sea level files

# Specifically designed to process SURFEX data (France scale)
surfex_path =  None # add surfex models in .h5 format

# Indicate the name of the regional DEM
dem_name = "DEM_test_75m_LAMB93.tif"
# dem_name = "BDALTI_bzh_75m.tif"
dem_path = dems_path + dem_name

dem = gdal.Open(dem_path)
proj = osr.SpatialReference(wkt=dem.GetProjection())
crs = int(proj.GetAttrValue('AUTHORITY',1))

# Import the library of watersheds to generate
library_path = test_path + 'watershed_library.csv' # each row is a study site
library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied

# Select from the library the interest catchment
watershed_name = 'Example' # add manually study site information in map units
mysite = library[library['watershed_name'] == watershed_name] # specific row

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Specify the hydrologic layers to clip
types_obs = ['streams','sections'] # list of shapefile name layers
fields_obs = ['FID','Persistanc'] # list of shapefile name columns to translate in a tif

#%% GENERATING WATERSHED

load = True
print('##### '+watershed_name.upper()+' #####')

# try:
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path, 
                              geology_path = geology_path, 
                              hydrology_path=hydrology_path,
                              oceanic_path=oceanic_path, 
                              piezometry_path=piezometry_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              types_obs=types_obs,
                              fields_obs=fields_obs)
# except:
#     print('There is a problem to generate the watershed object')

#%% SET PARAMETERS

# Choice the state of the simulation
sim_state = 'steady' # steady
first = 2010
last = 2019
time_step = 'M'

# Recharge from a csv
rec = pd.read_csv(climate_path+'_REC_'+time_step+'.csv', sep=';', index_col=[0], parse_dates=True)
rec = rec[(rec.index.year>=first) & (rec.index.year<=last)]
rec = rec.squeeze()
BV.forcing.update_recharge(values = rec / 1000, sim_state=sim_state)

# Finally the rehcarge is set as a value or a serie
R = BV.forcing.recharge # mm/month to m/month

# Plot to control recharge 
fig, ax = plt.subplots(1,1, figsize=(6,3))
ax.plot(R*1000, c='k', lw=0.5)

# Update hydrualic conductivity
K = 1e-5 * 3600 * 24 * 30 # m/second to m/month
BV.hydrodynamic.update_hyd_cond(K)

# Update aquifer thickness
E = 30 # m
BV.hydrodynamic.update_thickness(E)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = sim_state

#%% RUN MODEL

BV.run_modflow(ident=model_name, modpath_sim=False, calib=False, sink_fill=False, 
                lay_number=1, bottom=None, thick_exp=1., sea_level=None, cond_decay=0., 
                verbose=True)
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False, 
                    first=first, last=last, time_step='monthly')

#%% VISUALIZATION 3D

from groundwater_flow import vizualisation
vtk.VTK(BV, model_name)
visu = vizualisation.Vizualisation(BV, model_name)
visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines','watertable_depth'], view='south-west')

#%% PLOT SURFACE OUTPUTS

if sim_state=='transient':
    plots.SurfaceOutputs(R, simulations_folder, stable_folder, model_name, types_obs, freq_interv=12, save_gif=True)

#%% INTERACTIVE CROSS-SECTION

mpl.rcParams.update(mpl.rcParamsDefault)

# Modules
from IPython import get_ipython
get_ipython().run_line_magic('matplotlib', 'qt')

# Import data
Data = BV.geographic.dem_data
WT = imageio.imread(simulations_folder+model_name+'/_extraction/'+'watertable_elevation_(000).tif')

# Figure params
fig, main_ax = plt.subplots(figsize=(14, 14))
title = plt.suptitle('Interactive cross section head',y=0.98)
divider = make_axes_locatable(main_ax)
top_ax = divider.append_axes("top", 1.05, pad=0.2, sharex=main_ax)
right_ax = divider.append_axes("right", 1.05, pad=0.2, sharey=main_ax)
top_ax.xaxis.set_tick_params(labelbottom=False)
right_ax.yaxis.set_tick_params(labelleft=False)

# Axis names
main_ax.set_xlabel('X')
main_ax.set_ylabel('Y')
top_ax.set_ylabel('Z profile')
right_ax.set_xlabel('Z profile')

# Dimensions
xvalues = np.linspace(-1,1,Data.shape[1])
yvalues = np.linspace(-1,1,Data.shape[0])
xx, yy = np.meshgrid(xvalues,yvalues)

# Positions
pos = np.empty(xx.shape + (2,))
pos[:, :, 0] = xx
pos[:, :, 1] = yy

# V and H lines
cur_x = Data.shape[1] - 1
cur_y = Data.shape[0] - 1

# Data dem
dem_max = Data.max()
demprof = Data.astype(float)
demprof[demprof<0] = np.nan

# Data wt
wt_max = WT.max()
wtprof = WT.astype(float)
wtprof[wtprof<0] = np.nan

### Line cross-section : neighbours
x0, y0 = 15, 30 # These are in _pixel_ coordinates !
x1, y1 = 30, 10
num = int(np.hypot(x1-x0, y1-y0))
num = x1-x0
x, y = np.linspace(x0, x1, num), np.linspace(y0, y1, num)
zi = demprof[y.astype(np.int), x.astype(np.int)] # or: zi = scipy.ndimage.map_coordinates(z, np.vstack((y,x)))

# ### Line cross-section : cubic
# d_x = [500,200]
# d_y = [50,400]
# length = int(np.hypot(d_x[1]-d_x[0], d_y[1]-d_y[0]))
# xd, yd = np.linspace(d_x[0], d_x[1], length), np.linspace(d_y[0], d_y[1], length)
# zd = sp.ndimage.map_coordinates(zprof, np.vstack((yd,xd))) # Transpose ?
# demPlot = np.flip(demPlot,axis=0)

# Plot dem
demPlot = np.ma.masked_array(Data, mask=(Data<0))
main_ax.imshow(demPlot, origin='lower', cmap='terrain')
plt.gca().invert_yaxis()

# Scaling axis
main_ax.autoscale(enable=False)
right_ax.autoscale(enable=False)
top_ax.autoscale(enable=False)
right_ax.set_xlim(right=dem_max)
top_ax.set_ylim(top=dem_max)

# Plot lines
v_line = main_ax.axvline(cur_x, color='k', lw=2)
h_line = main_ax.axhline(cur_y, color='k', lw=2)
d_line = main_ax.plot((x0,x1),(y0,y1), 'white', '-')

# Plot dem cross-sections
dv_plot = demprof[:,int(cur_x)]
dv_plot[dv_plot == 0] = np.nan
h_plot = demprof[int(cur_y),:]
h_plot[h_plot == 0] = np.nan
dv_prof, = right_ax.plot(dv_plot,np.arange(xx.shape[0]), c='saddlebrown')
dh_prof, = top_ax.plot(np.arange(xx.shape[1]),h_plot, c='saddlebrown')
# dh_prof, = top_ax.plot(x, zi, 'b-')

# # Plot wt cross-sections
wv_plot = wtprof[:,int(cur_x)]
wv_plot[wv_plot == 0] = np.nan
wh_plot = wtprof[int(cur_y),:]
wh_plot[wh_plot == 0] = np.nan
wv_prof, = right_ax.plot(wv_plot,np.arange(xx.shape[0]), c='dodgerblue')
wh_prof, = top_ax.plot(np.arange(xx.shape[1]),h_plot, c='dodgerblue')
# wh_prof, = top_ax.plot(x, zi, 'b-')

plt.tight_layout()

# Animation interactive
def on_move_dem(event):
    if event.inaxes is main_ax:
        
        cur_x = event.xdata
        cur_y = event.ydata       
        
        dv_plot = demprof[:,int(cur_x)]
        dv_plot[dv_plot == 0] = np.nan
        dh_plot = demprof[int(cur_y),:]
        dh_plot[dh_plot == 0] = np.nan        
        v_line.set_xdata([cur_x, cur_x])
        h_line.set_ydata([cur_y, cur_y])
        dv_prof.set_xdata(dv_plot)
        dh_prof.set_ydata(dh_plot)
                
        fig.canvas.draw_idle()
        
def on_move_wt(event):
    if event.inaxes is main_ax:
        
        cur_x = event.xdata
        cur_y = event.ydata       
        
        wv_plot = wtprof[:,int(cur_x)]
        wv_plot[wv_plot == 0] = np.nan
        wh_plot = wtprof[int(cur_y),:]
        wh_plot[wh_plot == 0] = np.nan        
        v_line.set_xdata([cur_x, cur_x])
        h_line.set_ydata([cur_y, cur_y])
        wv_prof.set_xdata(wv_plot)
        wh_prof.set_ydata(wh_plot)
                
        fig.canvas.draw_idle()
   
fig.canvas.mpl_connect('motion_notify_event', on_move_dem)
fig.canvas.mpl_connect('motion_notify_event', on_move_wt)

#%%