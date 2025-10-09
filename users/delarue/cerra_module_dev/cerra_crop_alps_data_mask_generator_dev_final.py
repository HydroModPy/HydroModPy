# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 15:39:36 2025

@author: delarueo
"""


# TODO: comment function & clean aspect

#%%
import os
import shutil
import time
import xarray as xr
import numpy as np

import geopandas as gpd

from pywtraj import geohydroconvert as ghc

from scipy.spatial import cKDTree

import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point
import copy

from math import floor,ceil,sqrt

#%% Functions for module cerra 

def create_folder(folder_path):
    """
    Creates a folder if it doesn't already exist.

    Parameters:
    -----------
    folder_path : str
        Path to the folder where buffers will be stored.

    Returns:
    --------
    None
    """
    try:
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        path = folder_path
    except:
        print("Error - provide string is not a path - replace by local path")
        path = './'        
    return path
        
def generate_grid_file(ref_path, grid_path, attrs = dict(), coord_ids = dict(), verbose = False) :  
    
    data = xr.open_dataset(ref_path, mode='r', engine='netcdf4')
    lat = data.latitude.values
    lon = data.longitude.values
    data.close() 
    
    extras = {'description': 'Cerra data pixel grid coordinates',
              'grid_projection_type':  'Lambert conformal conical grid',
              'grid_projection_name':  'ERTS89-LCC',
              'espg': 6258}

    for [key, val] in attrs.items():
        extras[key] = val        

    grid = xr.Dataset( coords = {"latitude":  (("y", "x"), lat),
                                 "longitude": (("y", "x"), lon)},
                        attrs  = extras)
    
    grid.rename(coord_ids)  
    grid = ghc.georef(data = grid, crs = 6258)

    ghc.export(grid, grid_path)
    
    if verbose: 
        print(f'>> generate_grid_file from {ref_path}')
        print(f'>> generated file at {grid_path}')
        print(grid)        
       
    return grid
       
def plot_grid_points_near_polygon(dataset, polygon, distance_threshold=0.05, method = 'bound', display = True):
    """
    This function plots the grid points near the given polygon. 
    Only grid points within a specified distance threshold from the polygon will be plotted.
    """
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values

    # Create a list of grid points that are close to the polygon
    points_near_polygon = []

    # Create a Polygon object from the provided polygon (Shapely)
    if method == 'bound': # consider the rectangle surrounding the polygon instead of the detailed shape of the polygon
        polygon_coords = list(polygon.coords)
        polygon_coords = np.array([list(coords) for coords in polygon_coords]).T
        lat_min, lat_max  = polygon_coords[1].min(),polygon_coords[1].max() # extract polygon limits from coordonates
        lon_min, lon_max  = polygon_coords[0].min(),polygon_coords[0].max()
        polygon_bounds = [(lon_min,lat_min),(lon_max,lat_min),(lon_max,lat_max),(lon_min,lat_max),(lon_min,lat_min)]
        polygon_geom = Polygon(polygon_bounds)
        polygon_full = Polygon(polygon)
        
    elif method == 'polygon': 
        polygon_geom = Polygon(polygon)
    else:    
        raise ValueError("Unsupported method. Use one of: polygon, bound.")


    # Loop through each grid point and check if it's within the distance threshold from the polygon
    for lat, lon in zip(grid_lat.flatten(), grid_lon.flatten()):
        point = Point(lon, lat)
        if polygon_geom.distance(point) <= distance_threshold:  # Check if point is within distance threshold
            points_near_polygon.append((lat, lon))

    # Convert the points to a NumPy array for easier handling
    points_near_polygon = np.array(points_near_polygon)

    # Create a GeoDataFrame for the polygon
    gdf_area = gpd.GeoDataFrame({'geometry': [polygon_geom]}, crs="EPSG:4326")

    # Create a GeoDataFrame for the nearby points
    gdf_points = gpd.GeoDataFrame({'geometry': [Point(lon, lat) for lat, lon in points_near_polygon]}, crs="EPSG:4326")

    # Plot the polygon and nearby points on the map
    fig, ax = plt.subplots(figsize=(10, 10))

    # Plot the considered polygon area
    gdf_area.plot(ax=ax, color='lightyellow', edgecolor='black')

    # Plot the polygon if different from considered polygon area
    if method == 'bound':
        gdf_polygon = gpd.GeoDataFrame({'geometry': [polygon_full]}, crs="EPSG:4326")
        gdf_polygon.plot(ax=ax, color='lightblue', edgecolor='blue')    
    
    # Plot the nearby grid points
    gdf_points.plot(ax=ax, color='blue', marker='o', markersize=15, label="nearby grid points")

    # Set axis labels
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')

    # Add title and legend
    ax.set_title('Nearby Grid Points Relative to Polygon')
    ax.legend()

    if display :
        plt.show()
    return fig,ax 

def find_nearest_point(dataset, lat, lon, direction = 'all'):
    """
    Finds the nearest grid point in the specified direction from a given (lat, lon) coordinate using brute force.

    Parameters:
    dataset (xarray.Dataset): The grid dataset containing latitudes and longitudes.
    lat (float): Latitude of the reference point.
    lon (float): Longitude of the reference point.
    direction (str): Direction to search ('sw', 'se', 'nw', 'ne', 'all').

    Returns:
    tuple: Nearest latitude, longitude, and the index of the point in the dataset.
    """
    # Extract the grid coordinates
    grid_lat = copy.deepcopy(dataset.lat.values)
    grid_lon = copy.deepcopy(dataset.lon.values)
    shape = grid_lat.shape

    # Apply direction mask
    mask = {
        'sw': (grid_lat < lat) & (grid_lon < lon % 360),
        'se': (grid_lat < lat) & (grid_lon > lon % 360),
        'nw': (grid_lat > lat) & (grid_lon < lon % 360),
        'ne': (grid_lat > lat) & (grid_lon > lon % 360),
        'all': np.ones(shape)
    }.get(direction)
        
    if mask is None:
        raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne', 'all'.")

    # Mask the grid points outside the specified direction
    grid_lat[~mask] = np.nan
    grid_lon[~mask] = np.nan
        
    # If no points are found in the specified direction, raise an error
    if np.all(np.isnan(grid_lat)) or np.all(np.isnan(grid_lon)):
        raise ValueError(f"No points found in the {direction} direction.")

    # Initialize variables to track the minimum distance and the nearest point
    min_dist = np.inf
    nearest_lat = None
    nearest_lon = None
    nearest_idx = None

    # Brute force search for the nearest point in the specified direction
    # TODO: use a nother distance ?
    # TODO: consider better approach then brut force ?
    
    for i in range(shape[0]):
        for j in range(shape[1]):
            if not np.isnan(grid_lat[i, j]) and not np.isnan(grid_lon[i, j]):
                # Calculate the distance to the point
                dist = np.sqrt((grid_lat[i, j] - lat)**2 + (grid_lon[i, j] - lon)**2)
                if dist < min_dist:
                    min_dist = dist
                    nearest_lat = grid_lat[i, j]
                    nearest_lon = grid_lon[i, j]
                    nearest_idx = (i, j)

    # Return the coordinates of the nearest point and the original index
    return nearest_lat, nearest_lon, nearest_idx, min_dist

# TODO: method deux - keep distance en kilometre - metre
def generate_mask_from_polygon(polygon, grid, ratio = 2,
                               checkplot = True, verbose = False, mask_id = 'mask'):     
    # define verboseprint accordingly to parameters
    verboseprint = print if verbose else lambda *a, **k: None
    verboseprint('> START function generate_mask_from_polygon')
    
    # extract polygon point coordonates
    verboseprint('>> access catchement polygon coordonates')
    polygon_coords = list(polygon.geometry[0].coords) 
    polygon_coords = np.array([list(coords) for coords in polygon_coords]).T
    
    # extract polygon limits from coordonates
    verboseprint('>> identify catchement boundaries (rectangle circoncrit to the catchement polygone)')
    lon_min, lon_max  = polygon.bounds.minx.values[0] ,polygon.bounds.maxx.values[0]
    lat_min, lat_max  = polygon.bounds.miny.values[0] ,polygon.bounds.maxy.values[0] 

    verboseprint('>> identify on-grid catchement corners')
    polygon_corners = [[lon_min,lat_min,'sw'],[lon_max,lat_min,'se'],[lon_max,lat_max,'ne'],[lon_min,lat_max,'nw']]
    idx_mask_corners = []
    mask_corners = []  
    
    for [clon,clat,direction] in polygon_corners:
        verboseprint(f'>>> {direction} boundary corner : {clat} degN,{clon} degE')
        nearest_lat, nearest_lon, idx, dist = find_nearest_point(grid, clat, clon, direction = direction)    
        verboseprint(f">>>>>> nearest pixel: {nearest_lat} degN, {nearest_lon} degE (d = {dist})")
        idx_mask_corners.append(idx)
        mask_corners.append([nearest_lon,nearest_lat])

    # Define mask from idx_mask_corners - navigate grid [y,x]
    verboseprint('>> identify minimal mask')
    idx_mask_corners = np.array(idx_mask_corners).T     
    (extY,extX) = grid.lat.shape 
    minY, maxY = min(idx_mask_corners[0]), max(idx_mask_corners[0])
    minX, maxX = min(idx_mask_corners[1]), max(idx_mask_corners[1])
    rangeY = maxY - minY + 1
    rangeX = maxX - minX + 1    
    verboseprint(f'>> minimal mask : Y {minY}, {maxY} [{rangeY}] -  X {minX}, {maxX} [{rangeX}]')

    verboseprint('>> build mask')
    midY,midX = (minY+maxY)/2, (minX+maxX)/2
    minY = floor(midY - rangeY*ratio)
    maxY = ceil(midY + rangeY*ratio)
    minX = floor(midX - rangeX*ratio)
    maxX = ceil(midX + rangeX*ratio)        
    mask = np.zeros(grid.lat.shape)
    mask[minY:maxY+1,minX:maxX+1] = 1

    # visual check mask definition
    if checkplot:
        path = create_folder(checkplot)             
        verboseprint('>> create checkplot')
        lon_points = []
        lat_points = []
        for y in range(minY,maxY+1):
            for x in range(minX,maxX+1):
                lon_points.append(grid.lon.values[y,x])
                lat_points.append(grid.lat.values[y,x])
         
        fig,ax = plot_grid_points_near_polygon(grid, polygon.geometry[0], distance_threshold=0.4, method = 'bound', display = False)     
        ax.plot(lon_points, lat_points, ls = '',  color='red', marker='+', markersize=10, label="in mask")
        
        lon_corners = np.array(mask_corners).T[1]
        lat_corners = np.array(mask_corners).T[0]
        ax.plot(lat_corners,lon_corners, ls = '',  color='green', marker='x', markersize=10, label="pixel corners")
        
        plt.legend()
        plt.show()
        fig.savefig(f'{path}{mask_id}.png', bbox_inches='tight')
    
    verboseprint('> END function generate_mask_from_polygon')
    return mask

def crop_and_save(file_id, output_folder, data, mask):
        
    data['mask'] = (('y', 'x'), mask)  # Apply mask
    data = data.where(data.mask == 1)  # Apply the Alps mask
    data = data.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
    data = data.drop(['mask'])  # Drop unnecessary variables
    
    output_path = f'{output_folder}\{file_id}.nc'
    data.to_netcdf(output_path, mode='w') 

    return data

#%% Start time count
start = time.time()
end = start
print('> START\n')


#%% data access

# cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
# years = range(1984, 2023)
# variables = ['2m_temperature', 'total_precipitation']
# database_variables = {'2m_temperature' : 'air_temperature', 'total_precipitation':'total_precipitation'}
# catchements = ['alsg','dose','luit','mart','pass','sais','scha','urse','vill']
# reanalysis_name = 'cerra'
# catch_path = 'L:\_Alps\_waterwise_database\_time_series\_deployment_sites'

# Test kit
cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
years = range(1984, 1990)
variables = ['2m_temperature']
database_variables = {'2m_temperature' : 'air_temperature', 'total_precipitation':'total_precipitation'}
catchements = ['urse']
reanalysis_name = 'cerra'
catch_path = 'L:\_Alps\_waterwise_database\_time_series\_deployment_sites'

# Define path polygone
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'  
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    

print('> load grid')
grid_path = f'{cerra_path}cerra_grid_alps.nc'
grid = xr.open_dataset(grid_path, mode='r', engine='netcdf4')


#%% Create local netcdf for this mask from alps files

print('> create local netcdf')
for id_bv in catchements:
    print(f'>> {id_bv}')  
    print('>> generate mask')
    # TODO: change to shape file path
    polygon_path = polygon_path    
    # Load the polygon
    polygon = gpd.read_file(polygon_path)
    polygon = polygon.to_crs(epsg=4326) 
    mask = generate_mask_from_polygon(polygon, grid, ratio = 2, 
                                      checkplot = 'M:/crash_zone/',
                                      mask_id = f'mask_{id_bv}')   
    for var in variables:
        output_folder = f'{catch_path}\_{id_bv}\_climate\_{database_variables[var]}\_reanalysis\_{reanalysis_name}'
        create_folder(output_folder)
        print(f'>>> {var}\n>>>', end = '')
        for year in years:
            print(f' {year} -', end = '')
            
            # Define file paths
            folder_path = f'{cerra_path}{var}/'
            input_file_path = f'{folder_path}{year}/{year}_alps.nc'
            
            # Check if data available for given variable and year
            if os.path.isfile(input_file_path):                
                # Open dataset
                data = xr.open_dataset(input_file_path, mode='r', engine='netcdf4')

                # Process and save the buffer files
                crop_and_save(year, output_folder, data, mask)
                
                #TODO: combine netcdf ??
                data.close()
                
            else:
                print('\n>>>>>> no data')
        print()
        
#%% Final end message
# Display time elapsed for this year
step = end
end = time.time()
print(f'\n> {end - step:.2f} s - {end - start:.2f} s\n> END')


#%% other stuffs - trash

# def _find_nearest_point(dataset, lat, lon, direction="sw"):
#     # Extract the grid coordinates
#     grid_lat = copy.deepcopy(dataset.lat.values)
#     grid_lon = copy.deepcopy(dataset.lon.values)
#     shape = grid_lat.shape
    
#     # Apply direction mask
#     mask = {
#         'sw': (grid_lat < lat) & (grid_lon < lon % 360),
#         'se': (grid_lat < lat) & (grid_lon > lon % 360),
#         'nw': (grid_lat > lat) & (grid_lon < lon % 360),
#         'ne': (grid_lat > lat) & (grid_lon > lon % 360)
#     }.get(direction)
        
#     if mask is None:
#         raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne'.")

#     # Apply the mask to filter the grid points in the specified direction
#     # filtered_lat = grid_lat
#     # filtered_lon = grid_lon
#     grid_lat[~mask] = 'nan'
#     grid_lon[~mask] = 'nan'
        
#     # If no points are found in the specified direction, raise an error
#     if grid_lat.size == 0 or grid_lon.size == 0:
#         raise ValueError(f"No points found in the {direction} direction.")
    
#     # Flatten the filtered coordinates to use the k-d tree
#     points = np.column_stack((grid_lat.flatten(), grid_lon.flatten()))
    
#     # Create the k-d tree with the filtered grid points
#     tree = cKDTree(points)
    
#     # Find the index of the nearest point in the filtered grid
#     dist, idx = tree.query([lat, lon])
#     #TODO: which distance will be used
    
#     # Convert the index back to (i, j) coordinates in the filtered grid
#     nearest_idx = np.unravel_index(idx, shape)
    
#     # Return the coordinates of the nearest point
#     nearest_lat = grid_lat[nearest_idx]
#     nearest_lon = grid_lon[nearest_idx]
    
#     return nearest_lat, nearest_lon, nearest_idx, dist


# def create_buffer_folder(folder_path):
#     """
#     Creates a buffer folder if it doesn't already exist.

#     Parameters:
#     -----------
#     folder_path : str
#         Path to the folder where buffers will be stored.

#     Returns:
#     --------
#     None
#     """
#     if not os.path.exists(folder_path):
#         os.makedirs(folder_path)


# def process_and_save_buffer(var, year, buffer_folder, data, b_inf, b_sup):
#     """
#     Process the data in time slices and save the buffer files as netCDF.

#     Parameters:
#     -----------
#     var : str
#         Variable name (e.g., '2m_temperature', 'total_precipitation').
#     year : int
#         Year of the data.
#     buffer_folder : str
#         Path to the folder where buffer files will be saved.
#     data : xarray.Dataset
#         The dataset loaded from the input netCDF file.
#     b_inf : list
#         List of starting indices for each time slice buffer.
#     b_sup : list
#         List of ending indices for each time slice buffer.

#     Returns:
#     --------
#     list
#         List of file paths to the saved buffer files.
#     """
#     list_buffer_path = []
#     for b in range(len(b_inf)):
#         bi, bs = b_inf[b], b_sup[b]
        
#         buffer = data.isel(valid_time=range(bi, bs))  # Extract the time slice for this buffer
#         buffer['alps_mask'] = (('y', 'x'), mask)  # Apply mask
#         buffer = buffer.where(buffer.alps_mask == 1)  # Apply the Alps mask
#         buffer = buffer.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
#         buffer = buffer.drop(['expver', 'alps_mask'])  # Drop unnecessary variables
        
#         buffer_path = f'{buffer_folder}{b}.nc'
#         buffer.to_netcdf(buffer_path, mode='w')  # Save buffer as netCDF file
#         list_buffer_path.append(buffer_path)

#     return list_buffer_path


# def combine_buffers(list_buffer_path, alps_file_path):
#     """
#     Combines multiple buffer files into one netCDF file.

#     Parameters:
#     -----------
#     list_buffer_path : list
#         List of file paths to the individual buffer files.
#     alps_file_path : str
#         Path to save the combined netCDF file.

#     Returns:
#     --------
#     None
#     """
#     # Combine the separated buffer files into one large dataset
#     data = xr.open_dataset(list_buffer_path[0])
#     for f in list_buffer_path[1:]:
#         buffer = xr.open_dataset(f)
#         data = xr.concat([data, buffer], dim='valid_time')

#     data.to_netcdf(alps_file_path, mode='w')  # Save combined data
#     data.close()  # Close the dataset


# def clean_buffer_folder(buffer_folder):
#     """
#     Removes the buffer folder and all its contents.

#     Parameters:
#     -----------
#     buffer_folder : str
#         Path to the buffer folder to be removed.

#     Returns:
#     --------
#     None
#     """
#     if os.path.exists(buffer_folder) and os.path.isdir(buffer_folder):
#         shutil.rmtree(buffer_folder)  # Remove buffer folder and its contents


 
# # var = '2m_temperature'
# # year = 1984
# # alps_path = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/1984/1984_alps.nc'
# # data = xr.open_dataset(alps_path, mode='r', engine='netcdf4')
# # ref_path = f'{cerra_path}{var}/{year}/{year}_alps.nc'
# # grid_path = f'{cerra_path}cerra_grid_alps_.nc'
# # generate_grid_file(ref_path, grid_path, verbose = True)