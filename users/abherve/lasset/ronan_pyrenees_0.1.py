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
from src.watershed import climatic, driasclimat, driaseau, geographic, geology, geometric, hydraulic, \
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

watershed_names = ['PYRENEES']
from_xyvs = [None]

#%% LOAD

load = True
# load = False

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

# list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
#                'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
# list_vars = ['Debits','DRAINC','EVAPC','RUNOFFC','SWE','SWI'] # m3/s, mm, mm, mm, mm, -
        
# BV.add_driaseau('D:/Users/abherve/DRIAS_EAU/', list_models=['Model_01'], list_vars=['DRAINC']) # 'all'
"""
BV.add_driaseau('H:/SURFEX_CLIMATE_DATA/DRIAS_EAU/',
                list_models=['all'],
                list_vars=['DRAINC','EVAPC','RUNOFFC','SWE','SWI']) # 'all'
"""
#%% PROJECTION DRIAS EAU
"""
data_folder = stable_folder+'/driaseau/'

df = pd.DataFrame()
df.index = pd.date_range(start="1951-01-01",end="2099-12-31")

list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06','Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']

list_of_paths = []
for i in list_models:
    list_of_paths_model = glob.glob(os.path.join(data_folder+i+'/', '*.nc'))
    list_of_paths.extend(list_of_paths_model)

driaseau.driaseau_extract_values(data_folder, list_of_paths, df)
"""
#%% PROJECTION DRIAS CLIMATE

# list_models = ['Model_01','Model_02','Model_03','Model_04','Model_05','Model_06',
#                'Model_07','Model_08','Model_09','Model_10','Model_11','Model_12']
# list_vars = ['prtotAdjust',
#              'prsnAdjust',
#              'tasAdjust',
#              'tasmaxAdjust',
#              'tasminAdjust',
#              'hussAdjust',
#              'sfcWindAdjust',
#              'rldsAdjust',
#              'rsdsAdjust',
#              'FAO',
#              'Hg0175']
"""     
# BV.add_driaseau('D:/Users/abherve/DRIAS_EAU/', list_models=['Model_01'], list_vars=['DRAINC']) # 'all'
BV.add_driasclimat('H:/SURFEX_CLIMATE_DATA/DRIAS_CLIMAT/',
                   list_models=['all'],
                   list_vars=['prtotAdjust',
                              'prsnAdjust',
                              'tasAdjust',
                              'tasmaxAdjust',
                              'tasminAdjust',
                              'hussAdjust',
                              'sfcWindAdjust',
                              'rldsAdjust',
                              'rsdsAdjust',
                              'FAO', # # 'FAO' at the end
                              'Hg0175']) # 'all'
"""
#%% PROJECTION DRIAS EAU
"""
df = pd.DataFrame()
df.index = pd.date_range(start="1951-01-01",end="2099-12-31")
driasclimat.Driasclimat(stable_folder+'/driasclimat/', df)
"""
#%% ---- NOTES
