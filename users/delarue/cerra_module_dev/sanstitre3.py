# -*- coding: utf-8 -*-
"""
Created on Mon Mar 10 16:34:18 2025

@author: delarueo
"""

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt

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
    print(f"Direction: {direction}")
    mask = {
        'sw': (grid_lat < lat) & (grid_lon < lon % 360),
        'se': (grid_lat < lat) & (grid_lon > lon % 360),
        'nw': (grid_lat > lat) & (grid_lon < lon % 360),
        'ne': (grid_lat > lat) & (grid_lon > lon % 360)
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
    
    # Brute-force approach to find the nearest point
    distances = np.sqrt((filtered_lat - lat)**2 + (filtered_lon - lon)**2)  # Euclidean distance
    idx = np.argmin(distances)  # Find the index of the smallest distance
    
    # Get the nearest point from the filtered grid
    nearest_lat = filtered_lat[idx]
    nearest_lon = filtered_lon[idx]
    dist = distances[idx]  # The minimum distance
    
    # Find the original indices of the nearest point in the dataset
    # Reconstruct the original grid indices from the filtered ones
    original_idx = np.where(mask.flatten())[0][idx]
    original_row, original_col = np.unravel_index(original_idx, grid_lat.shape)
    
    return nearest_lat, nearest_lon, dist, original_row, original_col

# Example usage:
# Load the dataset (replace with your actual grid file)
grid_path = 'path_to_your_grid.nc'
grid = xr.open_dataset(grid_path, mode='r', engine='netcdf4')

# Example coordinates (adjust these as needed)
lat_point = 45.0  # Replace with your reference latitude
lon_point = 9.0  # Replace with your reference longitude

# Find the nearest point in the south-west direction
nearest_lat, nearest_lon, dist, original_row, original_col = find_nearest_point(grid, lat_point, lon_point, direction='sw')

print(f"Nearest point: Latitude {nearest_lat}, Longitude {nearest_lon}, Distance {dist}")
print(f"Original index in dataset: Row {original_row}, Column {original_col}")
