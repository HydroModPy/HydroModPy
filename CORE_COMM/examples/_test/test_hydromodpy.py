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
DIR = dirname(dirname(dirname(abspath(__file__))))
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
                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, forcing, watershed_display
from tools import toolbox, vtk
from watershed.data import hydrology, climatic, oceanic, piezometry
from groundwater_flow import visualization, modflow_display

#%% LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

# # Path to the git repositoty home page
# git_path = "C:/Users/alexa/Documents/GitHub/HydroModPy/CORE_COMM/"
# # Path to the data folder
# data_path = "C:/Users/alexa/OneDrive/_HydroDataPy/TEST/"
# # Path where the results will be stored
# out_path = 'C:/Users/alexa/Dropbox/HydroModPy/'

# Path to the git repositoty home page
git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "C:/Users/ronan/OneDrive/_HydroDataPy/TEST/"
# Path where the results will be stored
out_path = "D:/Users/abherve/TEST/"

#%% CORRECT PATHS

# We suggest to store the data in specific folder
dems_path = data_path + 'dem/'
hydrology_path = data_path + 'hydrology/' # add hydrographic shapefiles
modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe
shp_path = data_path + 'shp/'

intermittency_path = data_path + 'intermittency/'
hydrometry_path = data_path + 'hydrometry/'
piezometry_path = True # add piezometry data or nothing for automatic download
subbasin_path = True
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = None # add specific sea level files

# Specifically designed to process SURFEX data (France scale)
surfex_path =  data_path + 'surfex/' # add surfex models in .h5 format

# Indicate the name of the regional DEM
dem_name = "DEM_test_75m_LAMB93.tif" # dem_name = "BDALTI_bzh_75m.tif"
dem_path = dems_path + dem_name

dem = gdal.Open(dem_path)
proj = osr.SpatialReference(wkt=dem.GetProjection())
crs = int(proj.GetAttrValue('AUTHORITY',1))

# Model from a dem
from_dem = True
dem_path = dems_path + 'topoxyz_Uhigh.txt'
cell_size = 200

# Shp to build model
from_shp = None
# from_shp = shp_path + 'lambda.shp'

# Import the library of watersheds to generate
library_path = data_path + 'watershed_library.csv' # each row is a study site
library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied

# Select from the library the interest catchment
watershed_name = 'Dem' # add manually study site information in map units / 'Search' 
mysite = library[library['watershed_name'] == watershed_name] # specific row

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Specify the hydrologic layers to clip
types_obs = ['streams','sections'] # list of shapefile name layers
fields_obs = ['FID', 'Persistanc'] # list of shapefile name columns to translate in a tif

#%% GENERATING WATERSHED

load = True
print('##### '+watershed_name.upper()+' #####')

# try:
BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load,
                              from_shp=from_shp,
                              from_dem=from_dem,
                              cell_size=cell_size)

#%%

if load != True:
    BV.add_surfex(surfex_path) 
    BV.add_geology(geology_path) 
    BV.add_hydrology(hydrology_path,types_obs=types_obs,fields_obs=fields_obs)
    #BV.add_oceanic(oceanic_path)
    BV.add_hydrometry(hydrometry_path)
    BV.add_intermittency(intermittency_path)
    # BV.add_piezometry()
    BV.add_subbasin() 

# except:
#     print('There is a problem to generate the watershed object')

watershed_display.watershed_dem(BV)
watershed_display.watershed_local(dem_path, BV)

#%% REPROJECT LAYER

if crs == 4326:

    # Reproject raw DEM in WGS84 to specific UTM
    utm_crs = toolbox.reproject_tif(dem_path,
                                     data_path + 'dem/' + "DEM_test_75m_WGS84" + '.tif',
                                     data_path + 'dem/' + "DEM_test_75m_UTM" + '.tif')
    
    # Reproject shapefile layer to specific UTM
    toolbox.reproject_shp(data_path + 'hydrology/' + types_obs[0] + '.shp',
                           data_path + 'hydrology/' + types_obs[0] + '_utm' + '.shp',
                           utm_crs)
    
    # Convert longitude and latitude WGS84 to specific UTM
    utm_crs, x_utm, y_utm = toolbox.reproject_coord(-4.53924,
                                                     48.62315)

#%% SET PARAMETERS

# Choice the state of the simulation
sim_state = 'steady' # steady
sim_state = 'transient'
first = 2010
last = 2010
time_step = 'M'

# If recharge SURFEX is available
# BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic',
#                                   first_year = first, last_year = last, 
#                                   time_step = time_step, sim_state=sim_state)

# Finally the rehcarge is set as a value or a serie
# R = BV.forcing.recharge / 30 # m/month to m/day
# BV.forcing.update_recharge(values = R, sim_state=sim_state)

# Conceptual model
R = pd.Series([0.02,0.03,0.04,0.01,0.02,0.03,0.02,0.03,0.04,0.01,0.02,0.03,
               0.02,0.03,0.04,0.01,0.02,0.03,0.02,0.03,0.04,0.01,0.02,0.03,]) / 30
BV.forcing.update_recharge(R, sim_state='transient')

# Plot to control recharge 
# fig, ax = plt.subplots(1,1, figsize=(6,3))
# ax.plot(R*1000, c='k', lw=0.5)

# Update hydrualic conductivity
K = 1e-7 * 3600 * 24 # m/second to m/day
BV.hydrodynamic.update_hyd_cond(K)
KR = K / np.mean(R)

# Update aquifer thickness
E = 50 # m
BV.hydrodynamic.update_thickness(E)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = 'test_1'

#%% RUN MODEL

# x = plt.imshow(imageio.imread('D:/Users/abherve/TEST/Dem/results_stable/geographic/watershed_dem.tif'))

BV.run_modflow(ident=model_name,
                modpath_sim=True,
                first_only=False,
                sink_fill=False,
                box=False,
                lay_number=1,
                bottom=None, thick_exp=1.,
                cond_decay=0.,
                verbose=True)

#%% MODFLOW RESULTS

BV.results_modflow(ident=model_name, actual_date=True, start='2010-01-01', time_step='M')

# df = pd.read_csv('D:/Users/abherve/TEST/Explo/results_simulations/test_1/_watershed/_simulated_results.csv', sep=';')
# plt.plot(df.recharge)
# plt.plot(df.outflow_drain, c='red')

#%% VISUALIZATION 3D

# vtk.VTK(BV, model_name)
# visu = visualization.Visualization(BV, model_name)
# visu.visual3D(interactive=True,
#               object_list=['grid','watertable', 'watertable_depth','pathlines', 'surface_flow', 'drain_flow'], z_scale=10,
#               view='south-west', lines=200, cloc=(0.7,0.1))

vtk.VTK(BV, model_name)
visu = visualization.Visualization(BV, model_name)
visu.visual3D(interactive=True,
              object_list=['grid','watertable', 'watertable_depth', 'pathlines', 'surface_flow', 'drain_flow'], z_scale=1,
              view='south-west', lines=200, cloc=(0.7,0.1))

#%% PLOT SURFACE OUTPUTS

# x = np.load('C:/Users/alexa/Dropbox/HydroModPy/Explo/results_simulations/test_1/_watershed/watertable_depth.npy', allow_pickle=True).item()[0]
# x[x<0] = np.nan
# plt.imshow(x[0])

modflow_display.SurfaceOutputs(R, simulations_folder, stable_folder, model_name,
                               types_obs, freq_interv=12, save_gif=True)

#%% INTERACTIVE CROSS-SECTION

# Dem data
dem_data = BV.geographic.dem_data
# dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_box_buff_dem.tif')
# dem_data = imageio.imread(stable_folder+'/geographic/'+'watershed_dem.tif')

# Wt data
wt_data = imageio.imread(simulations_folder+model_name+'/_watershed/_tifs/'+'watertable_elevation_t(000).tif') # buffer size no masked

# River data
# river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif')
# river_data = imageio.imread(stable_folder+'/hydrology/'+'streams_fr.tif')
river_data = None

# Function
modflow_display.interactive_cross_section(dem_data, wt_data, river_data, interactive=True)

#%% NOTES


