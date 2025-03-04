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

#%%
## Case open one file
year = 1985
# Define path data
file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
# Initialize the object with the NetCDF file path        
data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')

# print(data)
# print()

# lat_min, lat_max = 43, 49
# lon_min, lon_max =  4, 17.5

#%%

mask = np.zeros([1069,1069])

mask[390:521,475:675] = 1

# plt.imshow(mask)
# plt.show()

#%%

data['alps_mask'] = (('y', 'x'), mask)
data = data.where(data.alps_mask == 1)
# print()
# print(data)

#%%

# plt.imshow(data.t2m.isel(time=0))
# plt.ylim(390,530)
# plt.xlim(470,680)

#%%

data = data.dropna("y", how="all").dropna("x", how="all")
# print()
# print(data)
# data.t2m.isel(time=0).plot()

#%%  
new_file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}_alps.nc'
data.to_netcdf(new_file_path)

#%% 
# data = xr.open_dataset(new_file_path, mode = 'r', engine = 'netcdf4')
# data.t2m.isel(time=0).plot()
















#%%
# polygon_mask = ((lat_min < latitudes) & (latitudes < lat_max) &
#         (lon_min < longitudes) & (longitudes < lon_max))
# #%%
# plt.imshow(polygon_mask)
# plt.xlim(575,600)   
# plt.ylim(445,465)     
# #%%
# print(polygon_mask)
# #%%

# # data['polygon_mask'] = (('y', 'x'), polygon_mask)
# # data = data.where(data.polygon_mask == 1)
# # data = data.dropna("y", how="all").dropna("x", how="all")

# # print()
# # print(data)

# #%%

# data.t2m.isel(time=0).plot()
# plt.xlim(575,600)   
# plt.ylim(445,465) 

#%%






# plt.ylim(390,530)
# plt.xlim(470,680)
# for Y in range(0,1068):
#     for X in range(0,1068):

#         lat = data.latitude[Y,X]
#         lon = data.longitude[Y,X]
#         test = (lat_min<lat and lat<lat_max and lon_min<lon and lon<lon_max)            
#         if test:
#             mask[Y,X] = 1 

#         print(f">> y{Y} x{X}")

