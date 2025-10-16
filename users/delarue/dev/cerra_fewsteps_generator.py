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
from shapely.geometry import Polygon

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


# polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
# polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
# # Load the polygon
# polygon = gpd.read_file(polygon_path)
# polygon = polygon.to_crs(epsg=4326) 


#%%
## Case open one file
year = 1984
# Define path data
file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
# Initialize the object with the NetCDF file path        
data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')
print()
print(data)
#%%
# # data.to_netcdf('L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/1984/1984_bis.nc',
#                mode='w', 
#                engine='h5netcdf')

#%% restructure data
latitudes = data.latitude.drop('latitude').drop('longitude')
longitudes = data.longitude.drop('latitude').drop('longitude')

data = data.drop('latitude')
data = data.drop('longitude')


data = data.assign({'latitude':  latitudes,'longitude': longitudes,
                    'x': data.x, 'y' : data.y})
data = data.rename({'valid_time': 'time'})
print()
print(data)

#%% cut data
timestep_index = range(10)
data_ts = data.isel(time = timestep_index)
print()
print(data_ts)

#%% save cut data
save = True
label = 'timecut'
verbose = True

print()
if save:    
    if isinstance(save,bool):
        folder = file_path[:-7]
        year = file_path[-7:-3]
        print(folder)
        new_file_path = f'{folder}{year}_{label}.nc'
        
    elif isinstance(save,str):
        if os.path.isdir(save):
            year = file_path[-7:-3]
            new_file_path = f'{save}{year}_{label}.nc'
    else:
        new_file_path = f'./{year}_{label}.nc'
        print('>> invalid save location\n>> data saved in the current folder\n>>')
        
    if verbose :
        info = f'>> data saved at {new_file_path}'
        print(info) 
    del data
    data_ts.to_netcdf(new_file_path,format="NETCDF4")
    del data_ts

# lat_min, lat_max = 43, 49
# lon_min, lon_max =  4, 17.5

# mask = np.zeros([1069,1069])
# for Y in range(0,1068):
#     for X in range(0,1068):
#         try:
#             lat = latitudes[Y,X]
#             lon = longitudes[Y,X]
#             test = (lat_min<lat and lat<lat_max and lon_min<lon and lon<lon_max)            
#             if test:
#                 mask[Y,X] = 1 
#         except Exception as e:
#             print(f">> error {e} - y{Y} x{X}")

