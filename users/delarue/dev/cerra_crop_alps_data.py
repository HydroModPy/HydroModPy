# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 15:39:36 2025

@author: delarueo
"""
import os
import shutil
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
import time
#%% Start time count
start = time.time()
print('> START')
#%% Data path and space to explore
cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
years = range(1985,2023)
variables = ['2m_temperature','total_precipitation']

#%% Standard : masks & buffer size
mask = np.zeros([1069,1069])
mask[390:521,475:675] = 1

n_buffer = 1000

#%% Define parameter specific to var + year
for var in variables:
    for year in years:
        # Define path data
        folder_path = '{cerra_path}{var}/'
        file_path = f'{folder_path}{year}/{year}.nc'
        alps_file_path = f'{folder_path}{year}/{year}_alps.nc'
        buffer_folder = f'{folder_path}{year}/buffer/'
        list_buffer_path = []


        # Create buffer folder if necessary
        if not os.path.exists(buffer_folder):
            os.makedirs(buffer_folder)

        print('>{year} load')     
        data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')
        print(data)
        print('>>>>> define buffer parameters') 
        n_ts = data.dims['valid_time']
        
        b_inf = [i*n_buffer for i in range(n_ts//n_buffer+1)]
        b_sup = [j for j in b_inf[1:]] + [n_ts]

#%% Splite and crop data
        print('>>>>> split & crop')
        # for b in range(len(b_inf)):
        for b in range(len(b_inf)):
            bi,bs = b_inf[b],b_sup[b]
            print(f'>>>>>{bi:4.0f}')  
            buffer = data.isel(valid_time = range(bi,bs))  
            buffer['alps_mask'] = (('y', 'x'), mask)  
            buffer = buffer.where(buffer.alps_mask == 1)  
            buffer = buffer.dropna("y", how="all").dropna("x", how="all") 
            buffer = buffer.drop(['expver','alps_mask'])    
            buffer_path = f'{buffer_folder}{b}.nc'
            buffer.to_netcdf(buffer_path, mode = 'w')
            list_buffer_path.append(buffer_path)
        
        buffer.close()
        data.close()

#%% Combine the separted crop file
        print('>>>>> combine')
        data = xr.open_dataset(list_buffer_path[0])
        for f in list_buffer_path[1:]:
            buffer = xr.open_dataset(f)
            data = xr.concat([data,buffer],dim='valid_time')
        
        data.to_netcdf(alps_file_path, mode = 'w') 
        buffer.close()   
        data.close()
        
#%% Remove all buffer files        
        print('>>>>> clean')
        if os.path.exists(buffer_folder) and os.path.isdir(buffer_folder):
            shutil.rmtree(buffer_folder)
            
#%% Display time since beginning
        end = time.time()        
        print(f'>>>>> {end - start} s\n')


print('> END')



