# -*- coding: utf-8 -*-
"""
Created on Mon Mar 24 11:59:54 2025

@author: delarueo

pyHelp input generator dev
chatgpt
"""
import geopandas as gpd
from shapely.geometry import Point
import math

from abc import ABC, abstractmethod
import pandas as pd
import rasterio
import matplotlib.pyplot as plt

import xarray as xr

import numpy as np

#%%


def display_grid_points(gdf):
    """
    Function to display the grid points on a plot using matplotlib.
    
    :param gdf: GeoDataFrame containing the grid points.
    """
    # Plot the GeoDataFrame
    fig, ax = plt.subplots(figsize=(10, 10))
    gdf.plot(ax=ax, ls = '', marker='.', color='red', markersize=5, label="Grid Points")
    
    # Add title and labels
    ax.set_title("Grid Points", fontsize=15)
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    
    ax.set_aspect('equal', adjustable='box')
    
    # Display the plot
    plt.legend()
    plt.show()
    
def meters_per_degree_longitude(latitude):
    """
    Calculate the distance (in meters) for one degree of longitude at a specific latitude.
    The Earth is approximated as a sphere, and the distance changes based on latitude.
    """
    earth_radius = 6378137  # Earth's radius in meters (WGS84)
    return (math.pi / 180) * earth_radius * math.cos(math.radians(latitude))

def grid_generator(bounds, step_meters):
    """
    Generate a grid of coordinates within a bounding box with a specific step size in meters.
    
    :param bounds: A tuple (min_lon, min_lat, max_lon, max_lat) defining the bounding box.
    :param step_meters: Step size in meters for the grid.
    :return: A GeoDataFrame containing the grid of points.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    
    # Convert step in meters to step in degrees for latitude
    degrees_per_meter_lat = 1 / 111320  # Approximate meters per degree latitude
    step_deg_lat = step_meters * degrees_per_meter_lat
    
    # List to store the coordinates
    coordinates = []
    
    # Latitude iteration

    lats = min_lat
    latitudes = []
    while lats <= max_lat:
        latitudes.append(lats)
        lats += step_deg_lat
    
    # Longitude iteration for each latitude
    for lat in latitudes:
        meters_per_deg_lon = meters_per_degree_longitude(lat)
        step_deg_lon = step_meters / meters_per_deg_lon
        
        lons = min_lon
        while lons <= max_lon:
            coordinates.append([lat, lons])
            lons += step_deg_lon
    
    # Create shapely Point geometries for the coordinates
    coordinates = np.array(coordinates)
    points = [Point(lon, lat) for lat, lon in coordinates]
    
    # Create a GeoDataFrame
    gdf = gpd.GeoDataFrame(geometry=points)
    df = pd.DataFrame({'latitude': coordinates.T[0][:],
                       'longitude': coordinates.T[1][:]})
    
    
    return gdf, df

def ncGrid2gdf(grid_file):
    grid = xr.open_dataset(grid_file, mode='r', engine='netcdf4')
    
    lat = grid.lat.values
    lon = grid.lon.values
    shape = lat.shape
    
    points = []
    yx = []
    for y in range(shape[0]):
        for x in range(shape[1]):
            points.append(Point(lon[y,x], lat[y,x]))
            yx.append((y,x))
    gdf = gpd.GeoDataFrame(geometry=points, crs="EPSG:4326")      
            
    return gdf,yx
    
def plot_multiple_geodataframes(gdfs, colors=None, markersize=[50], markershape = ['o'], alpha=0.5, 
                                title="Multiple GeoDataFrames", xlabel="Longitude", ylabel="Latitude",
                                labels = None):
    """
    Function to plot several GeoDataFrames on the same plot, where each GeoDataFrame represents 
    pixel center points.

    Parameters:
    - gdfs: List of GeoDataFrames to plot.
    - colors: List of colors for each GeoDataFrame. If None, default colors will be used.
    - markersize: Size of the points representing pixel centers.
    - alpha: Transparency of the points.
    - title: Title of the plot.
    - xlabel: Label for the x-axis.
    - ylabel: Label for the y-axis.
    """
    
    # Create a figure and axis
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Default colors if none are provided
    if colors is None:
        colors = ['red', 'blue', 'green', 'orange', 'purple']
        
    if labels is None:
        labels = [f'Raster {i}' for i in range(len(gdfs))]
    
    if len(markersize)<len(gdfs):
        ms = markersize[0]
        markersize = [ms for i in gdfs]
    
    if len(markershape)<len(gdfs):
        ms = markershape[0]
        markershape = [ms for i in gdfs]
    
    # Plot each GeoDataFrame in the list
    for i, gdf in enumerate(gdfs):
        gdf.plot(ax=ax, color=colors[i % len(colors)], label= labels[i], 
                 markersize=markersize[i], marker=markershape[i], alpha=alpha)
    
    # Add legend
    ax.legend()
    
    # Set title and labels
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    
    # Show the plot
    plt.show()

def find_closest_grid_point_idx(grid_gdf, target_point):
    """
    Find the closest grid point to a target point.
    
    Parameters:
    - grid_gdf: GeoDataFrame containing grid points.
    - target_point: The target Point geometry.
    
    Returns:
    - The closest grid point to the target point.
    """
    # Calculate distance from the target point to all grid points
    grid_gdf['distance'] = grid_gdf.geometry.distance(target_point)
    # Get the grid point with the smallest distance
    closest_idx = grid_gdf['distance'].idxmin()
    
    return closest_idx


def nearest_points_gdf(grid_gdf, target_point):
    # Convert target point to GeoSeries (GeoDataFrame)
    target_gdf = gpd.GeoDataFrame(geometry=[Point(target_point)], crs=grid_gdf.crs)
    
    # Calculate distance from each grid point to the target point
    grid_gdf['distance'] = grid_gdf.geometry.distance(target_gdf.geometry[0])
    
    # Sort the grid points by distance
    grid_gdf_sorted = grid_gdf.sort_values(by='distance')
    
    # Return the closest `num_nearest` points
    return grid_gdf_sorted
  

# def downscaleLaws(gridUp, gridUp_yx, gridDown, rule = 'nearest'):    
    
#     laws = []
#     for point in gridDown.geometry: 
#         print(point)
#         if rule == 'nearest':
#             idx = find_closest_grid_point_idx(gridUp,point)
#             yx = gridUp_yx[idx]
#             law = (lambda dataVar: dataVar[:,yx[0],yx[1]].values)
#             laws.append(law)
#         else:
#             law = (lambda x: x)
#             laws.append(law)
#     return laws
def calculate_internal_bounds(gdf, shrink_distance=0.1):
    """
    Function to calculate the internal bounds of a GeoDataFrame of points.
    This function computes the convex hull, shrinks it inward, and returns the bounds.

    Parameters:
    - gdf: GeoDataFrame containing points (geometry must be Point).
    - shrink_distance: Distance to shrink the convex hull (default is 0.5).

    Returns:
    - internal_bounds: A tuple (minx, miny, maxx, maxy) of the internal (shrunken) bounding box.
    """
    # Step 1: Compute the convex hull of all the points in the GeoDataFrame
    convex_hull = gdf.unary_union.convex_hull
    
    # Step 2: Shrink the convex hull by the specified shrink_distance using a negative buffer
    internal_polygon = convex_hull.buffer(-shrink_distance)
    
    # Step 3: Check if the resulting polygon is valid
    if internal_polygon.is_valid:
        # Return the bounds of the internal (shrunken) polygon
        internal_bounds = internal_polygon.bounds  # (minx, miny, maxx, maxy)
    else:
        # If the internal polygon is invalid, return the original convex hull's bounds
        internal_bounds = convex_hull.bounds
    
    return internal_bounds

def _downscale(data, var, gridUp, gridUp_yx, gridDown, rule = 'nearest', timestep = 'D'):       
               
    agg_rules = {'2m_temperature': 'mean',
                'total_precipitation': 'sum'}

    
    data = to_standard(data)
    dataVar = data[var]

    timeline = data['time'].values
    values = pd.DataFrame()
    values['time'] = pd.to_datetime(timeline, format='%d-%b-%Y %H:%M:%S')

    i = 0           
        
    for point in gridDown.geometry: 

        if rule == 'nearest':
            nearest = nearest_points_gdf(gridUp,point)
            idx = nearest.index.values[0]
            yx = gridUp_yx[idx]
            v = dataVar[:,yx[0],yx[1]].values

        elif rule == 'linear':
            nearest = nearest_points_gdf(gridUp,point)
            idx = nearest.index.values[:4]
            dist = nearest.distance.values[:4]
            
            v = np.zeros(dataVar[:,0,0].shape)
            for i in range(4):
                yx = gridUp_yx[idx[i]] 
                d = dist[i]
                v +=  dataVar[:,yx[0],yx[1]].values*d/dist.sum()

        else: 
            print('> _downscale rule - not available')
            v = []
        values[i] = pd.to_numeric(v, errors='coerce')  
        i += 1

    values.set_index('time', inplace=True)
    values = values.resample(timestep).agg(agg_rules[var])       
    
    return values

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
        't2m': '2m_temperature',
        'tp': 'total_precipitation'
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

        
#%%

cerra_file = 'M:/crash_zone/cerra_grid_urse.nc'


print('> open cerra grid as a GeoDataFrame and find boundaries')
gdf_cerraGrid,yx_cerraGrid = ncGrid2gdf(cerra_file)
cerra_area = calculate_internal_bounds(gdf_cerraGrid, shrink_distance=0.01)
print(cerra_area)
#%%
print('> generate GeoDataFrame of the pixel centers of the new grid')
step_meters = 5000  # Step size in meters

# Generate the grid
gdf_newGrid,df_newGrid = grid_generator(cerra_area, step_meters)

print('> display both grids')
plot_multiple_geodataframes([gdf_cerraGrid,gdf_newGrid], title ='Pixel centers of the grids', labels = ['cerra','pyhelp'], markersize = [100,10])
#%%

print('> for each help pixel define timeserie extractor rule')
# gdf_cerraGrid.to_crs(espg = 4326)
# gdf_newGrid.to_crs(espg = 4326)
# laws = downscaleLaws(gdf_cerraGrid,yx_cerraGrid,gdf_newGrid,rule = 'linear')
# df_newGrid = df_newGrid.T


#%%

agg_rules = {'2m_temperature': 'mean',
            'total_precipitation': 'sum'}

data_path = 'M:/crash_zone/1984.nc'
timestep = 'D'
var = '2m_temperature'
data = xr.open_dataset(data_path, mode='r', engine='netcdf4')
#%%
result = _downscale(data,var, gdf_cerraGrid, yx_cerraGrid, gdf_newGrid,rule = 'nearest', timestep = timestep)
#%%
# df_newGrid = pd.concat([df_newGrid,result])
print(df_newGrid)
print(result)
#%%

# df_newGrid_var = pd.concat([df_newGrid,values]).T






# df_newGrid_var['cid'] = df_newGrid_var.index.values
# df_newGrid_var.set_index('cid', inplace=True)

# data = pd.read_csv(file_path, sep=',')

# # Convert the 'Date' column to a datetime format
# station_data = pd.DataFrame()
# station_data['time'] = pd.to_datetime(data['Date'], format='%d-%b-%Y %H:%M:%S')

# # Extract the year for grouping
# station_data['year'] = station_data['time'].dt.year

# # Ensure numeric columns are correctly converted
# station_data['CRain'] = pd.to_numeric(data['CRain'], errors='coerce')  # Corrected Precipitation
# station_data['T'] = pd.to_numeric(data['T'], errors='coerce')          # Temperature

# station_data.set_index('time', inplace=True)

# #%%
# # Resample every 3-hours 
# station_data_3h = station_data.resample('3H').agg({
#     'CRain': 'sum',  # Summing precipitation over each 3-hour period
#     'T': 'mean'      # Taking the mean temperature over each 3-hour period
# })

# station_data_day = station_data.resample('D').agg({
#     'CRain': 'sum',  # Summing precipitation over each 3-hour period
#     'T': 'mean'      # Taking the mean temperature over each 3-hour period
# })








