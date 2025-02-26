# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 15:39:36 2025

@author: delarueo
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import math as m

import geopandas as gpd
from shapely.geometry import Point, Polygon

import rioxarray

import xarray as xr

import cartopy.crs as ccrs
import cartopy
import cartopy.feature as cfeature

import rasterio
from rasterio.plot import show
import numpy as np
import matplotlib.contour as contour

import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.ticker import LongitudeLocator, LatitudeLocator
from matplotlib.ticker import MaxNLocator

import netCDF4
import metpy

#%% File path collection
year = 1985
# Define path data
folder_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/'
file_path = f'{folder_path}{year}/{year}.nc'
alps_file_path = f'{folder_path}{year}/{year}_alps.nc'
list_buffer_path = []
#%% Alps mask standard
mask = np.zeros([1069,1069])
mask[390:521,475:675] = 1

#%%
print('>> INIT')
print('>> first load full year data set')      
data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')
print(data)
print('>> define buffer parameters') 
n_ts = data.dims['valid_time']
n_buffer = 1000
b_inf = [i*n_buffer for i in range(n_ts//n_buffer+1)]
b_sup = [j for j in b_inf[1:]] + [n_ts]

#%%
print('\n>>>>>> START BUFFER')
# for b in range(len(b_inf)):
for b in range(len(b_inf)):
    bi,bs = b_inf[b],b_sup[b]
    print(f'>>{bi:4.0f} create buffer')  
    buffer = data.isel(valid_time = range(bi,bs))
    print(f'>>>>>> add alps mask to buffer')  
    buffer['alps_mask'] = (('y', 'x'), mask)
    print(f'>>>>>> replace values out of the mask by NaN')  
    buffer = buffer.where(buffer.alps_mask == 1)
    print(f'>>>>>> drop only NaN columns and rows')  
    buffer = buffer.dropna("y", how="all").dropna("x", how="all")
    print(f'>>>>>> save buffer')      
    buffer_path = f'{folder_path}{year}/{year}_b{b}.nc'
    buffer.to_netcdf(buffer_path, mode = 'w')
    print(f'>>>>>> {buffer.valid_time[]}')
    print(f'>>>>>> {buffer_path}')
    list_buffer_path.append(buffer_path)

buffer.close()
data.close()

#%%

# data = xr.open_dataset(alps_file_path, mode = 'r', engine = 'netcdf4')

# mask = np.zeros([1069,1069])
# mask[390:521,475:675] = 1
# data['alps_mask'] = (('y', 'x'), mask)
# data = data.where(data.alps_mask == 1)
# data = data.dropna("y", how="all").dropna("x", how="all")
 
# new_file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}_alps.nc'
# data.to_netcdf(new_file_path,engine = 'h5netcdf')



