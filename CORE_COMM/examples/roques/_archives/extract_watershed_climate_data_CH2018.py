# -*- coding: utf-8 -*-
"""
Created on Fri Mar 25 11:24:25 2022

@author: LocalAdmin
"""

# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:05:41 2021

@author: Ronan Abhervé
"""

#TO BE DONE
#check the stream length calculation
#check numbers of events analyzed
#filter by doodness of fit


#%% GENERAL LIBRARIES

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

                 
#%% HYDROMODPY MODULES
                    
from watershed import watershed_root, watershed_display
from tools import toolbox, vtk
from groundwater_flow import visualization, modflow_display
from calibration import calib_root
from tools import vtk
from groundwater_flow import visualization
from tools import toolbox

#%% close windows explorer
import psutil
from subprocess import PIPE

#%% LAYOUT PLOT

#fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% PERSONAL PATHS

# Path to the git repositoty home page
git_path = "C:/Users/LocalAdmin/Documents/GitHub/HydroModPy/CORE_COMM/"
# Path to the data folder
data_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/Vallon_Nant/_data/"
# Path where the results will be stored
out_path = "D:/GoogleDrive/1.TRAVAIL/PYTHON/project/Vallon_Nant/_out/"


#%% FOLDER DATA PATHS

# Specify path or boolean to active/enable modules
dems_path = data_path + 'dem/' # reginal DEM or conceptual DEM
shp_path = data_path + 'shp/' # if you want run a model from a shapefile
modflow_path = data_path + 'modflow/' # add bin/ folder with necessary .exe

surfex_path =  data_path + 'surfex/' # add surfex models in .h5 format (France scale, else, specify None)
geology_path = data_path + 'geology/' # add geologic layers
oceanic_path = data_path + 'oceanic/' # add specific sea level files
hydrology_path = data_path + 'hydrology/' # add hydrographic shapefiles
hydrometry_path = data_path + 'hydrometry/' # add hydrometry data for automatic download
intermittency_path = data_path + 'intermittency/' # add intermittency data for automatic download
piezometry_path = True # add piezometry data for automatic download
subbasin_path = True # generate subbasins from stations or manual points

library_path = data_path + 'watershed_library_GRDC_alps_pyr.csv' # each row is a study site with outlet coordinates
dem_name = "eu_dem_v11_E30-40N20_clip_alps_polyg_EPSG3035.tif" # name of dem
dem_path = dems_path + dem_name



#%% 
#watershed_names = ['AP_6948360', 'AP_6948120']
# for i, j in points.iterrows():
#     if i>=15:
watershed_name = 'vallon_nant'
print('working on catchment' + watershed_name)
x = 4095461.4
y = 2575785.3

t = time.time()
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/' # necessary for plots
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'  # necessary for plots


#%%#############################
######## GENERATING WATERSHED
load = True
BV = watershed_root.Watershed(watershed_name=watershed_name,
                          dem_path=dem_path, 
                          out_path=out_path,
                          modflow_path=modflow_path,
                          library_path=library_path,
                          load=load,
                          regio_out=True, from_xy=[x,y,250,25])


# watershed_display.watershed_dem(BV)
# watershed_display.watershed_local(dem_path, BV)

#%%#############################
######## CLIMATE 
print('##')
print('I analyse the climate data')
#% Extract climate data from ERA5 netcdf file
# inspired from http://www.matteodefelice.name/post/aggregating-gridded-data/
# for names of variables https://collections.eurodatacube.com/reanalysis-era5-land-monthly-means/readme.html
main_folder = 'E:/climate_scenarios_ch2018/_/QMgrid/'

variables = ['pr','tas','tasmax','tasmin']

#create directory to store the data
directory = "climate"
parent_dir = stable_folder
path = os.path.join(parent_dir, directory)
os.makedirs(path,exist_ok=True)

# read the shapefile
bnd = gpd.read_file(stable_folder + 'geographic/buff.shp')#reading basin shapefile with geopandas
bnd = bnd.set_crs('epsg:3035')
bnd = bnd.to_crs(epsg = 4326)
bnd.head()

contour = gpd.read_file(BV.geographic.watershed_contour_shp)#reading basin shapefile with geopandas
contour = contour.set_crs('epsg:3035')
contour = contour.to_crs(epsg = 4326)


for i in variables:
    variable_name = str(i)
    print(variable_name)
    
    path_files = main_folder + str(i)
    
    files = os.listdir(path_files)
    
    for j in files:
        file = str(j)
        print(file)
        name_model = file[len(i)+8:-3]
        #print(name_model)

        #first create a directory 
        
        path2 = os.path.join(path, name_model)
        os.makedirs(path2,exist_ok=True)

        nc_to_read = os.path.join(main_folder, variable_name, file)
        # Read NetCDF
        d = xr.open_dataset(nc_to_read, chunks = {'time': 10})
        d = d.assign_coords(longitude=(((d.lon + 180) % 360) - 180)).sortby('lon')

        plt.figure(figsize=(12,8))
        ax = plt.axes()
        d.pr.isel(time = 0).plot(ax = ax)
        bnd.plot(ax = ax)

        array_to_clip = d.rio.write_grid_mapping(inplace=True)
        array_to_clip = array_to_clip.rio.write_crs("epsg:4326", inplace=True)
        d_clipped = array_to_clip.rio.clip(bnd.geometry)

        plt.figure(figsize=(12,8))
        ax = plt.axes()
        d_clipped.pr.isel(time = 10000).plot(ax = ax)
        contour.plot(ax = ax)

        filename_2 = path2 + '/' + variable_name + '.nc'
        
        d_clipped.to_netcdf(path=filename_2)
        d_clipped.close()
        
        d_mean = xr.DataArray.mean(d_clipped, dim={'lat', 'lon'}) #Mean calculation for all the variables of db over the basin
        
        plt.figure(figsize=(12,8))
        ax = plt.axes()
        d_mean.pr.plot(ax = ax)
        breakpoint()

        filename_3 = path2 + '/' + variable_name + '_mD.csv'
        
        dm = d_mean.to_pandas()
        dm =dm [variable_name]
        dm.to_csv(filename_3, header = [variable_name])
