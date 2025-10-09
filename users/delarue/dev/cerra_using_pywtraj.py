# -*- coding: utf-8 -*-
"""
Created on Wed Feb 26 12:02:51 2025

@author: delarueo
"""

import geopandas as gpd

import os
import shutil
import time
import xarray as xr
import numpy as np
from pywtraj import geohydroconvert as ghc

#%% Data path and space to explore
cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
years = range(1984, 2023)
variables = ['2m_temperature', 'total_precipitation']

#%% Standard: masks & buffer size

# Generate pixel lat/lon grid from data
var = '2m_temperature'
year = 1984

grid_path = f'{cerra_path}cerra_grid.nc'

#%%

ref_path = f'{cerra_path}{var}/{year}/{year}.nc'
grid_path = f'{cerra_path}cerra_grid.nc'

#%%

grid = xr.open_dataset(grid_path, mode='r', engine='netcdf4',decode_coords = 'all')
#%%
# Define path polygone
polygon_folder = r'L:/_poschiavino/_gis/bnd'    
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
# Load the polygon
polygon = gpd.read_file(polygon_path)
polygon = polygon.to_crs(epsg = 4326)  # to WGS84 coords system
polygon.plot()

#%%
grid_crs = ghc.georef(data = grid, crs = 6258)
print(grid_crs)

# reprj_ds = ghc.reproject(grid, resolution = 5.5, dst_crs = 4326, mask = polygon, x0 = 0, y0 = 0)