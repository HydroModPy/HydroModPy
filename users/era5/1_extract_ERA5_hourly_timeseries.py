# -*- coding: utf-8 -*-
"""
Created on Fri Mar 10 19:00:43 2023

@author: roquesc
"""

# General
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

# Warnings
import warnings
warnings.filterwarnings("ignore", message=".*An exception was ignored while fetching the attribute.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*`np.object` is a deprecated alias for the builtin `object`.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated. Use tobytes().*", category=DeprecationWarning)
warnings.filterwarnings("ignore")
# warnings.warn("You won't see this warning")

# for extraction ERA5
import geopandas as gpd
import xarray as xr 
import rioxarray

#%% close windows explorer
import psutil
from subprocess import PIPE
#%%
######## HERE IS THE CODE TO GENERATE THE BOUNDARY CONTOURS ########
## HYDROMODPY MODULES
                    
# from watershed import watershed_root, watershed_display
# from tools import toolbox, vtk
# from groundwater_flow import visualization, modflow_display
# from calibration import calib_root
# from tools import vtk
# from groundwater_flow import visualization
# from tools import toolbox
# #%% LAYOUT PLOT

# #fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

# #%% PERSONAL PATHS

# # Path to the git repositoty home page
# git_path = "D:/_GitHub/HydroModPy/CORE_COMM/"
# # Path to the data folder
# data_path = "G:/Mon Drive/1.TRAVAIL/PYTHON/project/alps_pyr/_data/"
# # Path where the results will be stored
# out_path = "G:/Mon Drive/1.TRAVAIL/PYTHON/project/Urse/_out"


# #%% FOLDER DATA PATHS

# # Specify path or boolean to active/enable modules
# dems_path = data_path + 'dem/' # reginal DEM or conceptual DEM
# shp_path = data_path + 'shp/' # if you want run a model from a shapefile
# modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe

# surfex_path =  data_path + 'surfex/' # add surfex models in .h5 format (France scale, else, specify None)
# geology_path = data_path + 'geology/' # add geologic layers
# oceanic_path = data_path + 'oceanic/' # add specific sea level files
# hydrology_path = data_path + 'hydrology/' # add hydrographic shapefiles
# hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
# intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
# piezometry_path = True # add piezometry data for automatic download
# subbasin_path = True # generate subbasins from stations or manual points

# dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
# dem_path = dems_path + dem_name

# ERA5_folder = '//vert/CHYN_OBSERVATOIRE_POSCHIAVINO/_poschiavino/_data/_era5_urse/_hourly/Jul-10-2023/'


# #find 
# path_points = 'G:/Mon Drive/1.TRAVAIL/PYTHON/project/Urse/_data/outlet_coordinate/stream_gauge_urse_EPSG3035.shp'
# points = gpd.read_file(path_points)
# dem_path = dems_path + dem_name

# watershed_name = "Urse"
# print('working on catchment #' + watershed_name)
# x = 4322204.2160169445 # points.loc[0,'X']
# y = 2579220.1833563875 # points.loc[0,'Y']

# stable_folder = out_path + '/' + watershed_name + '/results_stable/' # necessary for plots
# simulations_folder = out_path + '/' + watershed_name + '/results_simulations/'  # necessary for plots

#%% RUN WATERSHED_ROOT

# load = True

# BV = watershed_root.Watershed(watershed_name=watershed_name,
#                               dem_path=dem_path, 
#                               out_path=out_path,
#                               modflow_path=modflow_path,
#                               load=load,
#                               regio_out=True, from_xy=[x,y,500,100])

#%%#############################
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

