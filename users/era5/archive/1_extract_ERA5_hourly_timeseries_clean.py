# -*- coding: utf-8 -*-
"""
Created on Fri Mar 10 19:00:43 2023

@author: roquesc
"""

# General
import sys
from os.path import dirname, abspath
DIR = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(DIR)
import numpy as np
import pandas as pd
from osgeo import gdal, osr
import matplotlib.pyplot as plt
import time
import os
import os.path
from os import path

# Gis
import imageio
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# for extraction ERA5
import geopandas as gpd
import xarray as xr 
import rioxarray

#%% close windows explorer
import psutil
from subprocess import PIPE

######## HERE IS THE CODE TO EXTRACT THE CLIMATE DATA FROM A .netcdf FILE ############ 

print('##')
print('I analyse the climate data')
#% Extract climate data from ERA5 netcdf file
# inspired from http://www.matteodefelice.name/post/aggregating-gridded-data/
# for names of variables https://collections.eurodatacube.com/reanalysis-era5-land-monthly-means/readme.html


ERA5_folder = './_hourly/Nov-03-2024/'

stable_folder = './polygon_extract_era5/' # polygon of the area of interest

bnd = gpd.read_file(stable_folder + 'bnd_canfinal.shp')#reading basin shapefile with geopandas
bnd = bnd.set_crs('epsg:3035')
bnd = bnd.to_crs(epsg = 4326)
bnd.head()

contour = gpd.read_file(stable_folder + 'catchment_bnd_urse_streamgauge_EPSG3035.shp')#reading basin shapefile with geopandas
contour = contour.set_crs('epsg:3035')
contour = contour.to_crs(epsg = 4326)


files = os.listdir(ERA5_folder + 'download/')
# files = os.listdir(ERA5_folder)
for f in files:
    file = str(f)
    print(file)
    
    date = file[:-3]
    
    path_to_save = os.path.join(ERA5_folder, date)
    os.makedirs(path_to_save,exist_ok=True)
    
    nc_to_read = os.path.join(ERA5_folder + 'download/', file)

    # Read NetCDF
    d = xr.open_dataset(nc_to_read, chunks = {'time': 0})
    d = d.assign_coords(longitude=(((d.longitude + 180) % 360) - 180)).sortby('longitude')
    
    plt.figure(figsize=(12,8))
    ax = plt.axes()
    #d.t2m.isel(time = 0).plot(ax = ax)
    bnd.plot(ax = ax)
    
    array_to_clip = d.rio.write_grid_mapping(inplace=True)
    array_to_clip = array_to_clip.rio.write_crs("epsg:4326", inplace=True)
    # d_clipped = array_to_clip.rio.clip(bnd.geometry)
    # d_clipped2 = array_to_clip.rio.clip(contour.geometry)
    
    # plt.figure(figsize=(12,8))
    # ax = plt.axes()
    # # d_clipped.t2m.isel(time = 0).plot(ax = ax)
    # contour.plot(ax = ax)
    
    d_mean = xr.DataArray.mean(array_to_clip, dim={'latitude', 'longitude'}) #Mean calculation for all the variables of db over the basin
    # plt.figure(figsize=(12,8))
    # ax = plt.axes()
    # d_mean.tp.plot(ax = ax)
    
    #variables = ["t2m", "tp", "sd", "cdir", "tcsw", "ssr"]
    # variables = ['e', "es"]
    variables = ['es']
    
    for i in variables:
        variable_name = str(i)
        print('####extracting variable####')
        print(variable_name)
        
        #path_extract_era5 = out_path + watershed_name  + '/era5'
        
        # filename_extract_nc = path_extract_era5 + '/netcdf/' + variable_name + '.nc'
        
        # d_clipped.to_netcdf(path=filename_extract_nc)
        # d_clipped.close()
        
        filename_extract_csv = path_to_save + '/' + variable_name + '.csv'
        
        dm = d_mean.to_dataframe()
        dm = dm[variable_name]
        dm.to_csv(filename_extract_csv, header = [variable_name])
        print('extraction succeeded')

