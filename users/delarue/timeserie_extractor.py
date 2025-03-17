# -*- coding: utf-8 -*-
"""
Created on Thu Mar 13 16:22:14 2025

@author: delarueo
"""


#%%
import os
import shutil
import time
import xarray as xr
import numpy as np

import geopandas as gpd

import pandas as pd

from pywtraj import geohydroconvert as ghc

from scipy.spatial import cKDTree

import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point
import copy

from math import floor,ceil,sqrt

#%% Functions from geoDataFrame to array coords coords[0] llongitude coords[1]  latitude
def file2coords(file_path, src_crs = 3035, dst_crs = 4326):
    try:
        obj = gpd.read_file(file_path)  
    except:
        print("> error - invalid file path") 
        return False

    obj = obj.set_crs(epsg=src_crs)
    obj = obj.to_crs(epsg=dst_crs)
    obj = obj.geometry[0]
    obj_type = type(obj).__name__
    
    toCoords = {
        'Polygon':  lambda obj : np.array([list(coords) for coords in obj.exterior.coords]).T,
        'MultiPolygon': lambda obj : np.array([coord for p in [list(x.exterior.coords) for x in obj.geoms] for coord in p]).T,
        'LineString': lambda obj : np.array([list(coords) for coords in list(obj.coords)]).T
    }.get(obj_type)
    obj_coords = toCoords(obj)
    return obj_coords

def gdf2coords(gdf, src_crs = 3035, dst_crs = 4326):    
    if polygon.crs:
        gdf = gdf.to_crs(epsg=dst_crs)
    else:
        gdf = gdf.set_crs(epsg=src_crs)
        gdf = gdf.to_crs(epsg=dst_crs)
    obj = gdf.geometry[0]
    obj_type = type(obj).__name__
    
    toCoords = {
        'Polygon':  lambda obj : np.array([list(coords) for coords in obj.exterior.coords]).T,
        'MultiPolygon': lambda obj : np.array([coord for p in [list(x.exterior.coords) for x in obj.geoms] for coord in p]).T,
        'LineString': lambda obj : np.array([list(coords) for coords in list(obj.coords)]).T
    }.get(obj_type)

    if toCoords == None:
        print('> no protocole for this type of object (available - Polygon,Multipolygon,LineString')
        return False
    
    obj_coords = toCoords(obj)
    return obj_coords  

def extract_pixel_timeserie(start, end, variable, path, grid_id, y,x):
    """
    pixel_idx [y,x]
    """
    
    print('>> start extraction : ', end = '')    
    timeserie = pd.DataFrame({'time' : [],
                               variable : []})
    for year in range(start,end+1):
        print(f' {year} ', end = '')
        
        # Define file paths
        input_file_path = f'{path}{variable}/{year}/{year}{grid_id}.nc'
        
        # Check if data available for given variable and year
        
        if os.path.isfile(input_file_path):                
            # Open dataset
            data = xr.open_dataset(input_file_path, mode='r', engine='netcdf4')
            data = to_standard(data)
            
            timeline = data['time'].values
            values = data[variable][:,y,x].values
            
            df2 = pd.DataFrame({'time': timeline, variable: values})
            timeserie = pd.concat([timeserie,df2], axis=0, ignore_index=True)
            data.close()
            
        else:
            print(' no data', end = '')
            
        print(' -' , end = '')
    return timeserie     
            
def to_standard(dataset):
    """
    Apply necessary conversions and variable name changes
    to variables in the xarray dataset.
    Converts variables if needed (e.g., units conversion).
    
    :param dataset: The xarray dataset to process.
    :return: The modified xarray dataset.
    """
    STANDARD_CONVERSIONS = {
        't2m': lambda x: x - 273.15
        }
    STANDARD_VARIABLES = {
        't2m': '2m_temperature'
        }
    # Iterate over each variable in the dataset
    try:
        dataset = dataset.rename({'valid_time':'time'})     
    except:
        dataset = dataset
        
    for var_name in dataset.data_vars:
        if var_name in STANDARD_CONVERSIONS:
            # Apply the conversion if the variable has a corresponding function
            conversion_func = STANDARD_CONVERSIONS[var_name]
            dataset[var_name] = conversion_func(dataset[var_name])
            
        if var_name in STANDARD_VARIABLES:
            # Apply the name changes if the variable has a standard name
            new_name = STANDARD_VARIABLES[var_name]            
            dataset = dataset.rename({var_name : new_name})
    return dataset 


def grid_points_in_polygon(dataset, polygon, method = 'bound', display = True):
    """
    This function plots the grid points near the given polygon. 
    Only grid points within a specified distance threshold from the polygon will be plotted.
    """
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values
    shape = grid_lat.shape
    # Create a list of grid points that are close to the polygon
    points_near_polygon = []
    distance_threshold = 0
    
    polygon_coords = gdf2coords(polygon)

    # Create a Polygon object from the provided polygon (Shapely)
    if method == 'bound': # consider the rectangle surrounding the polygon instead of the detailed shape of the polygon
        lat_min, lat_max  = polygon_coords[1].min(),polygon_coords[1].max() # extract polygon limits from coordonates
        lon_min, lon_max  = polygon_coords[0].min(),polygon_coords[0].max()
        polygon_bounds = [(lon_min,lat_min),(lon_max,lat_min),(lon_max,lat_max),(lon_min,lat_max),(lon_min,lat_min)]
        polygon_geom = Polygon(polygon_bounds)
        polygon_full = polygon.geometry[0]
        
    elif method == 'polygon': 
        polygon_geom = polygon.geometry[0]
    else:    
        raise ValueError("Unsupported method. Use one of: polygon, bound.")


    # Loop through each grid point and check if it's within the distance threshold from the polygon
    list_pixel  = []
    list_point = []
    for i in range(shape[0]):
        for j in range(shape[1]):
            lat, lon  = grid_lat[i,j], grid_lon[i,j]
            point = Point(lon, lat)
            if polygon_geom.distance(point) <= distance_threshold:  # Check if point is within distance threshold
                list_pixel.append([i,j])
                list_point.append((lat,lon))
    
    if display: 
        list_point = np.array(list_point)
    
        gdf_area = gpd.GeoDataFrame({'geometry': [polygon_geom]}, crs="EPSG:4326")
        gdf_points = gpd.GeoDataFrame({'geometry': [Point(lon, lat) for lat, lon in list_point]}, crs="EPSG:4326")
    
        # Plot the polygon and nearby points on the map
        fig, ax = plt.subplots(figsize=(10, 10))
        gdf_area.plot(ax=ax, color='lightyellow', edgecolor='black', label = 'reseach area')
    
        if method == 'bound':
            gdf_polygon = gpd.GeoDataFrame({'geometry': [polygon_full]}, crs="EPSG:4326")
            gdf_polygon.plot(ax=ax, color='lightblue', edgecolor='blue',label = 'polygon')    
    
        if gdf_points.shape[0] > 0:
            gdf_points.plot(ax=ax, color='blue', marker='o', markersize=15, label="nearby grid points")
    
        # Set axis labels
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
    
        # Add title and legend
        ax.set_title('Points in Polygon')
        # ax.legend()
        plt.show()
        
    return list_pixel, list_point




            
#%%
cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
#%%
print('> load grid')
grid_path = f'{cerra_path}cerra_grid_alps.nc'
grid = xr.open_dataset(grid_path, mode='r', engine='netcdf4')


print('> load polygon')
polygon_path = 'M:/crash_zone/catchements/watershed_cont.shp'
polygon = gpd.read_file(polygon_path)
polygon = polygon.set_crs(epsg=3035)
polygon = polygon.to_crs(epsg=4326)

print('> find pixel in polygon')
list_pixel, list_point = grid_points_in_polygon(grid, polygon)

print(list_pixel)

#%%
# print('> extract timeserie')
# variable = '2m_temperature'
# start = 1984
# end = 2022 
# grid_id = '_alps'
# catchement = 'urse'
# output_path = f'M:/crash_zone/{variable}_{catchement}.csv'

# [y, x] = list_pixel[0]
# timeserie = extract_pixel_timeserie(start, end, variable, cerra_path, grid_id, y, x)
# timeserie.plot(x='time',y='2m_temperature',ls='',marker='.')

# timeserie.to_csv(output_path, index=False)

print('> this is the end')
    
    
    