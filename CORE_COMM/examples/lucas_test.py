# -*- coding: utf-8 -*-

#%% IMPORT MODULES

# Modules
import sys
import os
from os.path import dirname, abspath
DIR = dirname(dirname(abspath(__file__)))
sys.path.append(DIR)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import matplotlib as mpl
from osgeo import gdal
import imageio
import rasterio
import geopandas as gpd
from glob import glob
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.colors import LightSource
from matplotlib.pyplot import cm
from matplotlib.ticker import MaxNLocator
import warnings

warnings.filterwarnings("ignore", 
                        message=".*An exception was ignored while fetching the attribute.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*`np.object` is a deprecated alias for the builtin `object`.*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore", 
                        message=".*is deprecated. Use tobytes().*",
                        category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")
                                            
# HydroModPy modules
from watershed import watershed_root, forcing
from tools import tif_adds, serie_transf, tif_features, file_adds
from watershed.data import hydrology, climatic, oceanic, piezometry

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

#%% PATHS LOAD

# Users
git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
root_path= "D:/Users/abherve/HYDROMODPY/_data/"
out_path = "D:/Users/abherve/HYSTERESIS"

geology_path = None
hydrology_path = root_path + 'HYDROLOGY'
modflow_path = root_path + 'MODFLOW'
piezometry_path = None
oceanic_path = None
dem_path = root_path + "/DEM/" + "BDALTI_bzhext_75m.tif"

library_path = DIR + '/watershed' + '/watershed_library.csv'
surfex_path =  root_path + 'SURFEX/ebr/'
watershed_name = 'Canut'
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['name'] == watershed_name]

load = False

print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

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
                              load=load)

BV.forcing.update_recharge_surfex(clim_mod = 'REA', clim_sce='historic', first_year = 1960, last_year=2019, time_step = 'M', sim_state='steady')
BV.forcing.update_recharge([25/1000], 'steady')
BV.hydrodynamic.update_hyd_cond(1e-5*3600*24*30)
BV.run_modflow(sea_level=None, lay_number= 1, modpath_sim = False)

#%% RAW VTK

# from groundwater_flow import vizualisation
# visu = vizualisation.Vizualisation(BV, 'modflow')
# visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines','watertable_depth'], view='south-west')


