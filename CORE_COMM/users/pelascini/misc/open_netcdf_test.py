# -*- coding: utf-8 -*-
"""
Created on Fri Jul  8 10:37:20 2022

@author: Lucas
"""
#%% Drias.py

import geopandas as gpd
import pandas as pd
import os 
import sys
from os.path import dirname, abspath
import glob
import xarray as xr
from shapely.geometry import mapping
import numpy as np
xr.set_options(keep_attrs = True)
import rioxarray as rio
import rasterio
import matplotlib.pyplot as plt
import gc

#%%

path_qgis='C:/Users/Lucas/Desktop/HYDROMODPY/_data/DEM/19860820-19860824_var.nc'
shp_path='C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan/Morakot1/results_stable/geographic/watershed.shp'
data_folder='C:/Users/Lucas/Desktop/HYDROMODPY/Taiwan/Morakot1/results_stable/geographic'

with xr.open_dataset(path_qgis, decode_coords = 'all') as ds:
    ds.load()



def clip_netcdf(self, data_folder, path_qgis, shp_path):

    with xr.open_dataset(path_qgis, decode_coords = 'all') as ds:
        ds.load()
    # ds.sel(x = 76000, y = 2273000)

    # val = ds.DRAINC.values[0]
    # val = val[::-1]
    
    geodf = gpd.read_file(shp_path)
    geom = geodf.geometry.apply(mapping)
    clipped_ds = ds.rio.clip(geom, geodf.crs, all_touched = True, drop = True)
    # ds.rio.write_crs("epsg:2154", inplace = True)
    
    del ds
            
    outfile_path = os.path.join(data_folder, path_qgis.split('\\')[-1])
    clipped_ds.to_netcdf(outfile_path)
    
    del clipped_ds
    
    gc.collect()

    # geotif = 'D:/Users/abherve/DYNAMIC/Gael/results_stable/geographic/watershed.tif'
    # with xr.open_dataset(geotif) as mask_ds:
    #     mask_ds.load()
    # clipped_ds = ds.where(mask_ds, drop = True)
    
    
    
    
    #%% Alex Coche helps
    
    import xarray as xr
    import geopandas as gpd
    from shapely.geometry import mapping
    xr.set_options(keep_attrs = True)
    from affine import Affine
    import rasterio
    with xr.open_dataset(r"C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\19860820-19860824_var.nc", decode_coords = 'all') as ds:
        ds.load() #load as dataset
    ds.rio.write_crs('epsg:4326',inplace = True)
    
    x_res = 30 # res du fichier de sortie
    x_min = 280000 # x_mini pour lire le netcdf (coordonées de sortie)
    y_res = 30
    y_max = 2583000
    
    
    transform_ = Affine(x_res, 0.0 , x_min,
                  0.0, -y_res, y_max)
    
    height_ = 1000
    width_ = 1000
    
    
    
    ds_reproj = ds.rio.reproject(dst_crs = 'epsg:32651',
        transform = transform_,
        resampling = rasterio.enums.Resampling(5),# interpolation method (mean)
        shape = (height_, width_)
        )
    
    ds_reproj.to_netcdf(r'C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\19860820-19860824_reproj.nc')
    
    mask_df = gpd.read_file(r"C:\Users\Lucas\Desktop\HYDROMODPY\Taiwan\Morakot1\results_stable\geographic\watershed.shp") #load as geodataframe
    clipped_ds = ds_reproj.rio.clip(mask_df.geometry.apply(mapping), mask_df.crs, all_touched = True)
    clipped_ds.to_netcdf(r'C:\Users\Lucas\Desktop\HYDROMODPY\_data\DEM\19860820-19860824_clipped.nc')















    
    
        mask_df = gpd.read_file(r"blabla\mask.shp") #load as geodataframe

    clipped_ds = ds.rio.clip(mask_df.geometry.apply(mapping), mask_df.crs, all_touched = True)
    
    # Pour le netcdf :
    ds.rio.write_crs('epsg:32651', inplace = True)

    # Pour le masque :
    mask_df.set_crs('epsg:32651', inplace = True, allow_override = True)
    
    