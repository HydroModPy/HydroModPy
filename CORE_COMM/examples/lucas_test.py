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
root_path= "D:/Users/abherve/HYDROMODPY/_data/"
hydrology_path = root_path + 'HYDROLOGY' # cours d'eau
modflow_path = root_path + 'MODFLOW' # executable + bin
dem_path = root_path + "/DEM/" + "Taiwan_40m.tif"
surfex_path =  None
clm_path = None

out_path = "D:/Users/abherve/HYDROMODPY"

library_path = DIR + '/watershed' + '/watershed_library.csv'
watershed_name = 'Taiwan'
outlets = pd.read_csv(library_path, sep=';', header=0, engine='python')
outlets = outlets[outlets['name'] == watershed_name]

load = True

print('##### '+watershed_name.upper()+' #####')

stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

BV = watershed_root.Watershed(watershed_name=watershed_name,
                              dem_path=dem_path, 
                              out_path=out_path,
                              surfex_path=surfex_path, 
                              hydrology_path=hydrology_path,
                              modflow_path=modflow_path,
                              library_path=library_path,
                              load=load)

#%%

dem_data = imageio.imread(BV.geographic.watershed_dem)
dem_data[dem_data<0] = np.nan
# dem_data = np.ma.array(dem_data, mask = -99999)
x = plt.imshow(dem_data)

#%%

recharge = 0.75 * (3000/1000/365) # m/j
BV.forcing.update_recharge(recharge, 'steady') # steady or transient

BV.hydrodynamic.update_hyd_cond(1e-5*3600*24) # m/s en m/j

# BV.run_modflow(ident='test1', sea_level=None, lay_number=1, modpath_sim=True)

BV.calib_dichotomy(ident=None, calib=True, type_river='taiwan', climatic=recharge,
                    lay_number=1, thick=50, bottom=None, thick_exp=1., 
                    first=1, last=500, gap=1, porosity=0.01, sea_level=None, cond_decay=0.)

#%% RAW VTK

# from groundwater_flow import vizualisation
# visu = vizualisation.Vizualisation(BV, 'modflow')
# visu.visual3D(interactive=True, object_list=['grid','watertable','pathlines','watertable_depth'], view='south-west')
