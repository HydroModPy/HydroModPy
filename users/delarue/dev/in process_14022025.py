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
year = 1984
# Define path data
file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}_timecut.nc'
# Initialize the object with the NetCDF file path        
data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')

print(data)
print()

lat_min, lat_max = 43, 49
lon_min, lon_max =  4, 17.5

#%%
mask = np.zeros([1069,1069])


# Assuming data.latitude and data.longitude are 2D arrays (1069 x 1069)
latitudes = data.latitude.values
longitudes = data.longitude.values

# Create mask based on the latitudes and longitudes in one step using vectorized conditions
mask = ((lat_min < latitudes) & (latitudes < lat_max) &
        (lon_min < longitudes) & (longitudes < lon_max)).astype(int)

plt.imshow(mask)

#%%
data['alps_mask'] = (('y', 'x'), mask)
data = data.where(data.alps_mask == 1)
print()
print(data)
#%%
plt.imshow(data.t2m.isel(time=0))
plt.ylim(390,530)
plt.xlim(470,680)

#%%

data = data.dropna("y", how="all").dropna("x", how="all")
print()
print(data)
data.t2m.isel(time=0).plot()

#%% load polygon 

polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
# Load the polygon
polygon = gpd.read_file(polygon_path)
polygon = polygon.to_crs(epsg=4326) 

#%% build polygon mask with buffer size

buffer = 10

[[lat_min,lon_min,lat_max,lon_max]] = polygon.bounds.values
lat_ext = lat_max - lat_min
lon_ext = lon_max - lon_min

lat_min -= buffer*lat_ext
lat_max += buffer*lat_ext
lon_min -= buffer*lon_ext
lon_max += buffer*lon_ext

for l in [lat_min,lon_min,lat_max,lon_max]:
    print(l,end=' ')
    
#%%

# Get the offset for indexing (based on the first x and y values)
# x0, y0 = data.x.values[0], data.y.values[0]
latitudes = data.latitude.values
longitudes = data.longitude.values
polygon_mask = data.alps_mask.values
plt.imshow(polygon_mask)




















#%%
## Case open one file
year = 1984
# Define path data
file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}_timecut.nc'
# Initialize the object with the NetCDF file path        
data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')

print(data)
print()
#%%
# lcc_proj = cartopy.crs.
geo_proj = ccrs.PlateCarree()
lcc_proj = ccrs.LambertConformal(central_longitude  = 8, 
                                 central_latitude   = 50,
                                 false_easting      = +2656513.1201,
                                 false_northing     = +2788649.55497)


iY = 0
iX = 0

X = np.array([iX])*5500
Y = np.array([iY])*5500


tf = geo_proj.transform_points(lcc_proj, X, Y)
lon,lat = tf[0,0],tf[0,1]

print(f'lat,lon from transform: {lat},{lon}')
print(f'lat,lon from data:      {data.latitude.values[iY,iX]},{data.longitude.values[iY,iX]-360}')

#%%
lat0, lon0 = data.latitude.values[0,0], data.longitude.values[0,0]
latC, lonC = data.latitude.values[534,534], data.longitude.values[534,534]

from haversine import haversine_vector, Unit

p0 = (data.latitude.values[0,0], data.longitude.values[0,0]-360) # (latitude, longitude)
pC = (data.latitude.values[534,534], data.longitude.values[534,534])
pCs = (data.latitude.values[0,534], data.longitude.values[0,534])
pCe = (data.latitude.values[534,0], data.longitude.values[534,0]-360)

ds = haversine_vector([pC,p0],[pC,pCs], Unit.KILOMETERS)
de = haversine_vector([pC,p0],[pC,pCe], Unit.KILOMETERS)
print(f'ds,de: {ds},{de}')
# #%%
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

