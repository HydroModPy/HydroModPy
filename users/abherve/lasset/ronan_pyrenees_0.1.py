# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 10:49:18 2022

@author: ronan
"""

#%% LIBRARIES MODULES

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import glob
import geopandas as gpd
from shapely.geometry.polygon import LineString, Polygon
from shapely.ops import linemerge, unary_union, polygonize
from datetime import datetime
import os
import re
from matplotlib.dates import YearLocator, MonthLocator, DateFormatter
import scipy.stats as sp
import shapely.geometry as SG
import matplotlib.pylab as pl
import math
from pyproj import Transformer
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib as mpl
import rasterio
import fnmatch
import deepdish as dd
import matplotlib.dates as mdates
import flopy
import pickle
import random
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import MaxNLocator
import shutil

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show
from matplotlib.colors import LightSource
# import earthpy.spatial as es
# import earthpy.plot as ep

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
               
#%% HYDROMODPY

# Import HydroModPy modules
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(dirname(abspath(__file__)))))
sys.path.append(DIR)

import src
import importlib
importlib.reload(src)

from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, \
                          hydrography, hydrometry, intermittency, oceanic, \
                          piezometry, safransurfex, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large



def select_period(df, first, last):
    df = df[(df.index.year>=first) & (df.index.year<=last)]
    return df

#%% ---- CATCHMENT

#%% PATHS

git_path = 'D:/Users/abherve/GITHUB/HydroModPy-0.1/'
data_path = 'xxx'
# out_path = 'D:/Users/abherve/ONEDRIVE_UNINECHYN/OneDrive - unine.ch/SIMULATIONS/'
out_path = 'D:/Users/abherve/SIMULATIONS/'

fig_path = out_path + 'figures/'

# dem_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/12_Data/_GIS/dem/BDALTI_fr_75m.tif'
dem_path = 'D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/8_Modeling/Lasset/_data/_DEM/BDALTI_09_75m.tif'

subbasin_path = True # generate subbasins from stations or manual points
from_dem = None # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_shp = ['D:/Users/abherve/ONEDRIVE_PERSONNEL/OneDrive/UNINE/12_Data/_GIS/bounds/pyrenees.shp', 1]

watershed_names = ['Pyrenees']
from_xyvs = [None]

#%% LOAD

# load = True
load = False

for watershed_name, from_xyv in zip(watershed_names[:], from_xyvs[:]):
        
    print('##### '+watershed_name.upper()+' #####')
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xyv=from_xyv)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    print(BV.geographic.area.round(2))
    print(BV.geographic.slope.round(2))

    # try:
    #     visualization_watershed.watershed_local(dem_path, BV)
    #     visualization_watershed.watershed_dem(BV)
    # except:
    #     pass

#%% PROJECTION DRIAS EAU

# BV.add_driaseau('D:/Users/abherve/DRIAS_EAU/', list_models=['Model_01'], list_vars=['DRAINC']) # 'all'
BV.add_driaseau('H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/', list_models=['all'], list_vars=['all']) # 'all'

#%% ---- NOTES
