# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% ---- LIBRAIRIES

#%% DEFAULT SITE PACKAGES

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
warnings.filterwarnings("ignore")

# Libraries need to be installed if not
import numpy as np
import pandas as pd

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

#%% HYDROMODPY ROOT PATH

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)

cwd = os.getcwd()
if cwd == root_dir:
    print("Root path directory is: {0}".format(cwd))
else:
    os.chdir(root_dir)
    print("Root path directory is: {0}".format(cwd))

#%% HYDROMODPY IMPORT MODULES

# Import HydroModPy modules
from src import watershed_root
from src.watershed import climatic, geographic, geometric, hydraulic, hydrography, hydrometry, intermittency, lithology, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PATHS

#%% INFORM PERSONAL

example_path = root_dir + "/examples/01_conceptual unconfined aquifer/"
data_path = example_path + "data/"
out_path = 'C:/Users/ronan/Documents/SIMULATIONS/HYDROMODPY/'

#%% ---- CASES

#%% CHOICE CASE

case = 'FromLIB'
# case = 'FromDEM'
# case = 'FromSHP'
# case = 'FromXYV'

#%% CASE 1: MODEL AREA FROM LIB

if case == 'FromLIB':
    dem_path = data_path + 'regional dem.tif'
    load = False
    watershed_name = 'FromLIB'
    from_lib = os.path.join(data_path,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

#%% CASE 2: MODEL AREA FROM DEM

if case == 'FromDEM':
    dem_path = data_path + 'conceptual dem.tif'
    load = False
    watershed_name = 'FromDEM'
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = [dem_path, 100] # [path, cell size]
    from_shp = None # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

#%% CASE 3: MODEL AREA FROM SHP

if case == 'FromSHP':
    dem_path = data_path + 'regional dem.tif'
    load = False
    watershed_name = 'FromSHP',
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = [data_path + 'conceptual shp.shp', 10], # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

#%% CASE 4: MODEL AREA FROM XYV

if case == 'FromXYV':
    dem_path = data_path + 'regional dem.tif'
    load = False
    watershed_name = 'FromXYV',
    from_lib = None # os.path.join(root_dir,'watershed_library.csv')
    from_dem = None # [path, cell size]
    from_shp = [data_path + 'conceptual shp.shp', 10], # [path, buffer size]
    from_xyv = None # [x, y, snap distance, buffer size]
    bottom_path = None # path
    modflow_path = os.path.join(root_dir,'bin/')
    save_object = True

#%% ---- WATERSHED

#%% EXTRACED AREA

print('##### '+watershed_name.upper()+' #####')

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

visualization_watershed.watershed_dem(BV)
visualization_watershed.watershed_local(dem_path, BV)

#%% ADDING DATA

# # Specify the hydrologic layers to clip
# types_obs = ['streams','sections'] # list of shapefile name layers  #JR:Parameters
# fields_obs = ['FID','Persistanc'] # list of shapefile name columns to translate in a tif #JR:Parameters

# BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

# BV.add_hydrodynamic()
# BV.add_forcing()
# BV.add_oceanic(oceanic_path)

#%% ---- END CODE

os.chdir(root_dir)
