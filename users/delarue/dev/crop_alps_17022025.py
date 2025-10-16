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

#%%
## Case open one file


for year in range(1985,1986):
    mask = np.zeros([1069,1069])    
    mask[390:521,475:675] = 1 
    
    print(f'>> {year}')
    # Define path data
    file_path = f'D:\{year}.nc'
    # Initialize the object with the NetCDF file path        
    data = xr.open_dataset(file_path, mode = 'r', engine = 'netcdf4')    
    
    print(f'>> {year} open')
    data = data.isel(valid_time=[0,10])
    # data.close()
    # del data
    print(f'>> {year} cut')
    data.load()
    data['alps_mask'] = (('y', 'x'), mask)
    data = data.where(data.alps_mask == 1) 
    data = data.dropna("y", how="all").dropna("x", how="all")
    print(data)
    print(f'>> {year} cut data')    
    new_file_path = f'D:/{year}_cut.nc'
    # print(f'>> {year} define path')
    data.load()
    data.to_netcdf(new_file_path)
    data.close()
    
#%%    
    data.to_netcdf(new_file_path)
    print(f'>> {year} cut save')
    data.close()
    
#%%    
    # data['alps_mask'] = (('y', 'x'), mask)
    # data = data.where(data.alps_mask == 1) 
    # data = data.dropna("y", how="all").dropna("x", how="all")
      
    # new_file_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}_alps.nc'
    # data.to_netcdf(new_file_path)
    # del data










