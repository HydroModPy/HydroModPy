# -*- coding: utf-8 -*-
"""
Created on Mon Mar 10 15:46:20 2025

@author: delarueo
"""
import os
import numpy as np
import xarray as xr
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point
from scipy.spatial import cKDTree

import math
import haversine as hs   
from haversine import Unit
 


def find_nearest_point(dataset, lat, lon, direction):
    """
    Finds the nearest grid point in the specified direction from a given (lat, lon) coordinate.
    Uses a brute-force approach to find the nearest point.

    Parameters:
    dataset (xarray.Dataset): The grid dataset containing latitudes and longitudes.
    lat (float): Latitude of the reference point.
    lon (float): Longitude of the reference point.
    direction (str): Direction to search ('sw', 'se', 'nw', 'ne').

    Returns:
    tuple: Nearest latitude, longitude, distance to the point, and original indices of the point in the dataset.
    """
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values
    
    # Apply direction mask
    mask = {
        'sw': (grid_lat < lat) & (grid_lon < lon % 360),
        'se': (grid_lat < lat) & (grid_lon > lon % 360),
        'nw': (grid_lat > lat) & (grid_lon < lon % 360),
        'ne': (grid_lat > lat) & (grid_lon > lon % 360)
    }.get(direction)
        
    if mask is None:
        raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne'.")
        
    # # Optionally visualize the mask with imshow for debugging
    # plt.imshow(mask, cmap='gray', origin='lower')
    # plt.title(f"Direction mask for {direction}")
    # plt.show()
    
    # Apply the mask to filter the grid points in the specified direction
    filtered_lat = grid_lat[mask]
    filtered_lon = grid_lon[mask]

    print(filtered_lon)

    if filtered_lat.size == 0 or filtered_lon.size == 0:
        raise ValueError(f'No points found in the {direction} direction.')
    
    # Brute-force approach to find the nearest point
    dist = 100000
    ny = 1069
    nx = 1069
    loc_ref = (lat,lon)

    for y in grid.y.values:
        for x in grid.x.values:
            if mask[y,x]:
                point_lat = grid_lat[y,x]
                point_lon = grid_lon[y,x]
                point_lon = (point_lon//180)*(point_lon-360) + ((point_lon//180-1)%2)*point_lon
                loc_point = (point_lat,point_lon)
                d =hs.haversine(loc_ref,loc_point, unit = Unit.KILOMETERS)
                print(d)
                if d<= dist:
                    dist = d
                    ny, nx = y,x
    print(ny,nx,dist)
    # Get the nearest point from the filtered grid
    nearest_lat = filtered_lat[idx]
    nearest_lon = filtered_lon[idx]
    dist = distances[idx]  # The minimum distance
    
    # Find the original indices of the nearest point in the dataset
    # Reconstruct the original grid indices from the filtered ones
    original_idx = np.where(mask.flatten())[0][idx]
    original_row, original_col = np.unravel_index(original_idx, grid_lat.shape)
    
    return nearest_lat, nearest_lon, dist, original_row, original_col,distances

def __find_nearest_point(dataset, lat, lon, direction):
    """
    Finds the nearest grid point in the specified direction from a given (lat, lon) coordinate.

    Parameters:
    dataset (xarray.Dataset): The grid dataset containing latitudes and longitudes.
    lat (float): Latitude of the reference point.
    lon (float): Longitude of the reference point.
    direction (str): Direction to search ('sw', 'se', 'nw', 'ne').

    Returns:
    tuple: Nearest latitude, longitude, distance to the point, and original indices of the point in the dataset.
    """
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values
    
    # Apply direction mask
    print(f"Direction: {direction}")
    mask = {
        'sw': (grid_lat < lat) & (grid_lon < lon%360),
        'se': (grid_lat < lat) & (grid_lon > lon%360),
        'nw': (grid_lat > lat) & (grid_lon < lon%360),
        'ne': (grid_lat > lat) & (grid_lon > lon%360)
    }.get(direction)
        
    if mask is None:
        raise ValueError("Invalid direction. Choose from 'sw', 'se', 'nw', 'ne'.")
        
    # Optionally visualize the mask with imshow for debugging
    plt.imshow(mask, cmap='gray', origin='lower')
    plt.title(f"Direction mask for {direction}")
    plt.show()
    
    # Apply the mask to filter the grid points in the specified direction
    filtered_lat = grid_lat[mask]
    filtered_lon = grid_lon[mask]

    if filtered_lat.size == 0 or filtered_lon.size == 0:
        raise ValueError(f'No points found in the {direction} direction.')
    
    # Use KDTree for efficient nearest neighbor search
    tree = cKDTree(np.column_stack((filtered_lat, filtered_lon)))
    dist, idx = tree.query([lat, lon])

    # Get the nearest point from the filtered grid
    nearest_lat = filtered_lat[idx]
    nearest_lon = filtered_lon[idx]

    # Find the original indices of the nearest point in the dataset
    # Reconstruct the original grid indices from the filtered ones
    original_idx = np.where(mask.flatten())[0][idx]
    original_row, original_col = np.unravel_index(original_idx, grid_lat.shape)
    
    return nearest_lat, nearest_lon, dist, original_row, original_col

def _find_nearest_point(dataset, lat, lon, direction="sw"):
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values
    
    # Filter the grid based on the specified direction
    if direction == "sw":
        # South-West: lat < lat_point and lon < lon_point
        mask = (grid_lat < lat) & (grid_lon < lon)
    elif direction == "se":
        # South-East: lat < lat_point and lon > lon_point
        mask = (grid_lat < lat) & (grid_lon > lon)
    elif direction == "nw":
        # North-West: lat > lat_point and lon < lon_point
        mask = (grid_lat > lat) & (grid_lon < lon)
    elif direction == "ne":
        # North-East: lat > lat_point and lon > lon_point
        mask = (grid_lat > lat) & (grid_lon > lon)
    else:
        raise ValueError("Unsupported direction. Use one of: southwest, southeast, northwest, northeast.")
    
    # Apply the mask to filter the grid points in the specified direction
    filtered_lat = grid_lat[mask]
    filtered_lon = grid_lon[mask]
    
    # If no points are found in the specified direction, raise an error
    if filtered_lat.size == 0 or filtered_lon.size == 0:
        raise ValueError(f"No points found in the {direction} direction.")
    
    # Flatten the filtered coordinates to use the k-d tree
    points = np.column_stack((filtered_lat.flatten(), filtered_lon.flatten()))
    
    # Create the k-d tree with the filtered grid points
    tree = cKDTree(points)
    
    # Find the index of the nearest point in the filtered grid
    dist, idx = tree.query([lat, lon])
    
    # Convert the index back to (i, j) coordinates in the filtered grid
    nearest_idx = np.unravel_index(idx, filtered_lat.shape)
    
    # Return the coordinates of the nearest point
    nearest_lat = filtered_lat[nearest_idx]
    nearest_lon = filtered_lon[nearest_idx]
    
    return nearest_lat, nearest_lon, nearest_idx, dist

def _plot_grid_points_near_polygon(dataset, polygon, distance_threshold=0.05, method='bound', lat_point=None, lon_point=None, nearest_lat=None, nearest_lon=None):
    """
    Plots the grid points near a given polygon and indicates the nearest point.

    Parameters:
    dataset (xarray.Dataset): The grid dataset containing latitudes and longitudes.
    polygon (shapely.geometry.Polygon): The polygon within which to find nearby grid points.
    distance_threshold (float): The distance threshold to consider grid points near the polygon.
    method (str): The method used to define the polygon area ('bound' or 'polygon').
    lat_point (float): Latitude of the reference point.
    lon_point (float): Longitude of the reference point.
    nearest_lat (float): Latitude of the nearest grid point.
    nearest_lon (float): Longitude of the nearest grid point.
    """
    # Extract grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values

    # Generate polygon bounds or use the polygon directly
    if method == 'bound':
        polygon_coords = np.array(list(polygon.geometry[0].coords)).T
        lat_min, lat_max = polygon_coords[1].min(), polygon_coords[1].max()
        lon_min, lon_max = polygon_coords[0].min(), polygon_coords[0].max()
        polygon_geom = Polygon([(lon_min, lat_min), (lon_max, lat_min), (lon_max, lat_max), (lon_min, lat_max)])
    elif method == 'polygon':
        polygon_geom = polygon
    else:
        raise ValueError("Method should be either 'bound' or 'polygon'.")

    # Find points near the polygon
    nearby_points = [(lat, lon) for lat, lon in zip(grid_lat.flatten(), grid_lon.flatten())
                     if polygon_geom.distance(Point(lon, lat)) <= distance_threshold]
    
    # Convert to numpy array for easier handling
    nearby_points = np.array(nearby_points)

    # Plot polygon and nearby points
    fig, ax = plt.subplots(figsize=(10, 10))
    gdf_area = gpd.GeoDataFrame({'geometry': [polygon_geom]}, crs="EPSG:4326")
    gdf_area.plot(ax=ax, color='lightyellow', edgecolor='black')

    # Plot nearby grid points
    gdf_points = gpd.GeoDataFrame({'geometry': [Point(lon, lat) for lat, lon in nearby_points]}, crs="EPSG:4326")
    gdf_points.plot(ax=ax, color='blue', marker='o', markersize=5, label="Nearby Grid Points")

    # Plot nearest point (if available)
    if nearest_lat is not None and nearest_lon is not None:
        ax.plot(nearest_lon, nearest_lat, color='red', marker='x', markersize=10, label="Nearest Point")

    # Plot original reference point (if available)
    if lat_point is not None and lon_point is not None:
        ax.plot(lon_point, lat_point, color='green', marker='o', markersize=10, label="Original Point")

    # Customize plot
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Nearby Grid Points Relative to Polygon')
    ax.legend()

    plt.show()

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
    gdf_points.plot(ax=ax, color='blue', marker='o', markersize=5, label="Nearby Grid Points")

    # Set axis labels
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')

    # Add title and legend
    ax.set_title('Nearby Grid Points Relative to Polygon')
    ax.legend()

    if display :
        plt.show()
        
    return fig,ax 
#%%
# Example usage:

# Load the dataset (replace with your actual grid file)
grid_path = 'L:\_Alps\_public_database\_climate\cerra_forecast\cerra_grid.nc'
grid = xr.open_dataset(grid_path, mode='r', engine='netcdf4')


# Load the polygon (replace with your actual shapefile)
# Define path polygone
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
polygon = gpd.read_file(polygon_path)
polygon = polygon.to_crs(epsg=4326)  # Make sure the polygon is in EPSG:4326

# Example coordinates
lat_min, lon_min = polygon.bounds.maxx.values[0], polygon.bounds.maxy.values[0]  # Use polygon bounds as reference
# print(lat_min,lon_min)

# Find the nearest grid point to the South-West of the polygon (example direction)
nearest_lon, nearest_lat, dist, y, x, distances = find_nearest_point(grid, lat_min, lon_min, direction= 'ne')
print(x,y)
#%%
# Plot the results
# plot_grid_points_near_polygon(grid, polygon, distance_threshold=0.1, method='bound', 
                              # lat_point=lat_min, lon_point=lon_min, nearest_lat=nearest_lat, nearest_lon=nearest_lon)
                              
fig,ax = plot_grid_points_near_polygon(grid, polygon.geometry[0], distance_threshold=0.1, method = 'bound', display = True)
#%%
ax.plot(nearest_lat,nearest_lon, color='red', marker='+', markersize=10, label="Nearest Point")
plt.show()