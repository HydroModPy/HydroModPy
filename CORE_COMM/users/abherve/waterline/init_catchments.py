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

# Plot
from matplotlib_scalebar.scalebar import ScaleBar
from rasterio.plot import show

# Gis
import imageio
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
               
#%HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display, forcing
from watershed.data import climatic
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root

# LAYOUT PLOT

fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% ---- CATCH

#%% PATH WATERSHED

git_path = "D:/Users/abherve/GITHUB/HydroModPy/CORE_COMM/"
data_path = "C:/Users/ronan/OneDrive/UNINE/5_Waterline/Data/"
out_path = "C:/Users/ronan/Documents/SIMULATIONS/WATERLINE/CATCHMENTS/"
res_path = 'C:/Users/ronan/OneDrive/UNINE/5_Waterline/Hydromodpy/Catchments/'
modflow_path = 'D:/Users/abherve/ONEDRIVE/OneDrive - Université de Rennes 1/HYDRODATAPY/HydroDataPy/SOFTWARE/MODFLOW/' # add bin/ folder with necessary .exe

### Resampling
"""
wbt.resample(
    data_path+'DEM_2m.tif', 
    data_path+'DEM_10m.tif', 
    cell_size=10, 
    base=None, 
    method="cc")
wbt.modify_no_data_value(
    data_path+'DEM_10m.tif', 
    new_value="-99999")

with rasterio.open(data_path+'DEM_10m.tif') as src:
    data = src.read()
    ras_meta = src.profile
    ras_meta['crs'] = 'EPSG:2056'
with rasterio.open(data_path+'DEM_10m.tif', "w", **ras_meta) as dest:
    dest.write(data)
"""

subbasin_path = True # generate subbasins from stations or manual points
from_dem = False # True or False if the process start from a given DEM of xyz file
cell_size = None # specify new resolution from a given DEM or None
from_xy = []
from_shp = None # specify a path if process start from a given shapefile

watershed_names = ['Vosvozis',
                   'Hoal',
                   'Kocinka',
                   'Temmes',
                   'Canut',
                   'Lasset',
                   'Poschiavino']

# watershed_names = ['Temmes']

# watershed_names = ['Canut']
# watershed_names = ['Hoal']

#%% GENERATE WATERSHED

load = True

for watershed_name in watershed_names[:]:
    
    dems_path = data_path + '_Europe/' + 'Topography/' # reginal DEM or conceptual DEM        

    # if watershed_name == 'Vosvozis':
    #     dem_name = 'EUDTM_Greece.tif'
    # if watershed_name == 'Hoal':
    #     dem_name = 'EUDTM_Austria-Poland.tif'
    # if watershed_name == 'Kocinka':
    #     dem_name = 'EUDTM_Austria-Poland.tif'
    # if watershed_name == 'Temmes':
    #     dem_name = 'EUDTM_Finland.tif'
    # if watershed_name == 'Canut':
    #     dem_name = 'EUDTM_Brittany.tif'
    # if watershed_name == 'Lasset':
    #     dem_name = 'EUDTM_Pyrenees.tif'
    # if watershed_name == 'Poschiavino':
    #     dem_name = 'EUDTM_Alps.tif'
    
    raw_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'.tif'
    
    x = imageio.imread(raw_dem_path)
    plt.imshow(np.ma.masked_where(x<0, x))
    
    # Depending on the choices
    library_path = data_path + 'watershed_library_wgs84.csv'
    library = pd.read_csv(library_path, sep=';') # each row is a study site with outlet coordinates
    lib = library[library['watershed_name']==watershed_name]
    
    # REPROJECT LAYER

    # All metric should be in meters (UTM or Lambert) during process
    # If your projection files is WGS84 (EPSG:4326), these tools could reproject layers
    # Below few examples to convert your data
    
    # d = gdal.Open(dem_path)
    # proj = osr.SpatialReference(wkt=d.GetProjection())
    # crs = int(proj.GetAttrValue('AUTHORITY',1))
    # d = None
    crs = None

    # if crs == 4326:
    
    # Convert longitude and latitude WGS84 to specific UTM
    utm_crs, x_utm, y_utm = toolbox.reproject_coord(lib['x_outlet'].values[0],
                                                    lib['y_outlet'].values[0])
    
    from_xy = [x_utm, y_utm, 300, 10]
    # print(utm_crs) 
    
    if watershed_name == 'Vosvozis':
        from_xy = [x_utm, y_utm, 2000, 10]
    
    if watershed_name == 'Temmes':
        from_xy = [x_utm, y_utm, 1000, 10]
    
    # Reproject raw DEM in WGS84 to specific UTM
    wgs_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'_wgs84'+'.tif'
    utm_dem_path = dems_path+'EUDTM_Frame_'+watershed_name+'_utm'+str(utm_crs.split(':')[-1])+'.tif'
    utm_crs = toolbox.reproject_tif(raw_dem_path,
                                    wgs_dem_path,
                                    utm_dem_path)
    # # Reproject shapefile layer to specific UTM
    # toolbox.reproject_shp(data_path + 'hydrology/' + types_obs[0] + '.shp',
    #                       data_path + 'hydrology/' + types_obs[0] + '_utm' + '.shp',
    #                       utm_crs)
        
    print('##### '+watershed_name.upper()+' #####')
    print(utm_crs)
    
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=utm_dem_path, 
                                  out_path=out_path,
                                  modflow_path=modflow_path,
                                  library_path=library_path,
                                  load=load,
                                  from_shp=from_shp,
                                  from_dem=from_dem,
                                  from_xy=from_xy,
                                  cell_size=cell_size)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots  
  
    try:
        print(BV.geographic.area.round(2))
        print(BV.geographic.slope.round(2))
    except:
        pass
    
    try:
        watershed_display.watershed_dem(BV)
        watershed_display.watershed_local(utm_dem_path, BV)
    except:
        pass
            
#%% DATA WATERSHED

types_obs = ['xxx']
fields_obs = ['fid']

hydrology_path = 'xxx'

import rasterio as rio

for watershed_name in watershed_names[:]:
    
    print('##### '+watershed_name.upper()+' #####')
               
    BV = watershed_root.Watershed(watershed_name=watershed_name,
                                  dem_path=dem_path, 
                                  out_path=out_path,
                                  load=True)
    
    stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
    simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/' 
    
    BV.add_hydrology(hydrology_path, types_obs=types_obs, fields_obs=fields_obs)

    BV.add_hydrodynamic()
    BV.add_forcing()
    
    try:
        watershed_display.watershed_dem(BV)
        watershed_display.watershed_local(dem_path, BV)
    except:
        pass
    
#%% ---- NOTES


