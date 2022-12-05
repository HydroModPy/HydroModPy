# -*- coding: utf-8 -*-
"""
Created on Fri Jul  8 16:05:28 2022

@author: Lucas

inspired by https://www.earthdatascience.org/courses/use-data-open-source-python/hierarchical-data-formats-hdf/use-netcdf-in-python-xarray/
"""

#%%

import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
# netCDF4 needs to be installed in your environment for this to work
import xarray as xr
import rioxarray as rxr
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import seaborn as sns
import geopandas as gpd
import earthpy as et
#%%

# The (online) url for a MACAv2 dataset for max monthly temperature
data_path = "http://thredds.northwestknowledge.net:8080/thredds/dodsC/agg_macav2metdata_tasmax_BNU-ESM_r1i1p1_historical_1950_2005_CONUS_monthly.nc"

max_temp_xr  = xr.open_dataset(data_path)  
# View xarray object
max_temp_xr


climate_crs = max_temp_xr.rio.crs
climate_crs




max_temp_xr["air_temperature"]["lat"].values[:5]

print("The min and max latitude values in the data is:", 
      max_temp_xr["air_temperature"]["lat"].values.min(), 
      max_temp_xr["air_temperature"]["lat"].values.max())
print("The min and max longitude values in the data is:", 
      max_temp_xr["air_temperature"]["lon"].values.min(), 
      max_temp_xr["air_temperature"]["lon"].values.max())


#%% test on my data
data_path = 'C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/19860820-19860824_var.nc'

CLM4  = xr.open_dataset(data_path) 
CLM4
CLM4_crs=CLM4.rio.crs
CLM4_crs


#%%
from netCDF4 import Dataset
ds = Dataset("C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/19860820-19860824_var.nc")
print(ds.variables.keys())







