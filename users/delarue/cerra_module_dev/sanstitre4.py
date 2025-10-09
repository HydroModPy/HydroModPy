# -*- coding: utf-8 -*-
"""
Created on Mon Mar 10 14:55:30 2025

@author: delarueo
"""

import numpy as np
import xarray as xr
from scipy.spatial import cKDTree
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point

def find_nearest_point(dataset, lat, lon, direction="southwest"):
    # Extract the grid coordinates
    grid_lat = dataset.lat.values
    grid_lon = dataset.lon.values
    
    # Filter the grid based on the specified direction
    if direction == "southwest":
        mask = (grid_lat < lat) & (grid_lon < lon)
    elif direction == "southeast":
        mask = (grid_lat < lat) & (grid_lon > lon)
    elif direction == "northwest":
        mask = (grid_lat > lat) & (grid_lon < lon)
    elif direction == "northeast":
        mask = (grid_lat > lat) & (grid_lon > lon)
    else:
        raise ValueError("Unsupported direction. Use one of: southwest, southeast, northwest, northeast.")
    
    # Apply the mask to filter the grid points in the specified direction
    filtered_lat = grid_lat[mask]
    filtered_lon = grid_lon[mask]
    
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

def plot_grid_points_near_polygon(dataset, polygon, distance_threshold=0.05):
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
    polygon_geom = Polygon(polygon)

    # Loop through each grid point and check if it's within the distance threshold from the polygon
    for lat, lon in zip(grid_lat.flatten(), grid_lon.flatten()):
        point = Point(lon, lat)
        if polygon_geom.distance(point) <= distance_threshold:  # Check if point is within distance threshold
            points_near_polygon.append((lat, lon))

    # Convert the points to a NumPy array for easier handling
    points_near_polygon = np.array(points_near_polygon)

    # Create a GeoDataFrame for the polygon
    gdf_polygon = gpd.GeoDataFrame({'geometry': [polygon_geom]}, crs="EPSG:4326")

    # Create a GeoDataFrame for the nearby points
    gdf_points = gpd.GeoDataFrame({'geometry': [Point(lon, lat) for lat, lon in points_near_polygon]}, crs="EPSG:4326")

    # Plot the polygon and nearby points on the map
    fig, ax = plt.subplots(figsize=(10, 10))

    # Plot the polygon
    gdf_polygon.plot(ax=ax, color='lightblue', edgecolor='black')

    # Plot the nearby grid points
    gdf_points.plot(ax=ax, color='blue', marker='o', markersize=5, label="Nearby Grid Points")

    # Set axis labels
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')

    # Add title and legend
    ax.set_title('Nearby Grid Points Relative to Polygon')
    ax.legend()

    plt.show()

# Example: Assume the dataset is already loaded as 'dataset'
# dataset = xr.open_dataset('your_file.nc')  # Load your xarray dataset here
# Data path and space to explore
cerra_path = 'L:/_Alps/_public_database/_climate/cerra_forecast/'
years = range(1984, 2023)
variables = ['2m_temperature', 'total_precipitation']

# Standard: masks & buffer size

# Generate pixel lat/lon grid from data
var = '2m_temperature'
year = 1984

ref_path = f'{cerra_path}{var}/{year}/{year}.nc'
grid_path = f'{cerra_path}cerra_grid.nc'
# Example coordinates to test
lat_point = 45.0
lon_point = 4.1
dataset = xr.open_dataset(grid_path, mode='r', engine='netcdf4')
# Example polygon (could be any polygon, here a square for illustration)
polygon_coords = [(4.0, 45.0), (4.5, 45.0), (4.5, 45.5), (4.0, 45.5)]  # Example coordinates for a square polygon

# Call the function to plot grid points near the polygon (within a distance threshold of 0.05 degrees)
plot_grid_points_near_polygon(dataset, polygon_coords, distance_threshold=0.05)
