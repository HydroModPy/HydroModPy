"""

Created on 2023.

@author: Clément Roques

"""

#%% ---- LIBRAIRIES

# PYTHON PACKAGES

import sys
import os
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated since Matplotlib 3.*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
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
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# ROOT DIRECTORY

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
# root_dir = dirname(dirname(os.getcwd())) 
sys.path.append(root_dir)
cwd = os.getcwd()
if not cwd == root_dir:
    os.chdir(root_dir)
print("Root path directory is: {0}".format(root_dir.upper()))

# HYDROMODPY MODEULES

import src
import importlib
importlib.reload(src)
from src import watershed_root
from src.watershed import climatic, geographic, geology, geometric, hydraulic, hydrography, hydrometry, intermittency, oceanic, piezometry, subbasin
from src.modeling import downslope, modflow, modpath, timeseries
from src.display import visualization_watershed, visualization_results, export_vtuvtk
from src.tools import toolbox, folder_root
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- PERSONAL PATHS

#example_path = os.path.join(root_dir, "examples/00_simplified example presentend in the paper")
data_path = "G:/Mon Drive/_travail/_python/project/alps_pyr/_data/"
out_path = "D:/_projects/_Emme/"
# To change the folder path: out_path = folder_root.update_root_folder_results()
# To search folder path: out_path = folder_root.root_folder_results()

#%% ---- EXTRACT CATCHMENT

# Name of the study site
watershed_name = 'Emme'
print('##### '+watershed_name.upper()+' #####')

# Regional DEM
dems_path = data_path + 'dem/' # reginal DEM or conceptual DEM
dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
dem_path = dems_path + dem_name

# Outlet coordinates of the catchment
from_xyv = [4149402.8482353324, 2647996.013545164, 150, 1 , 'EPSG:3035']

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