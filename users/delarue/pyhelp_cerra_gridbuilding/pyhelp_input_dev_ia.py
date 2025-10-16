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

# Function to calculate the distance in meters per degree of longitude at a given latitude
def meters_per_degree_longitude(latitude):
    """
    Calculate the distance (in meters) for one degree of longitude at a specific latitude.
    The Earth is approximated as a sphere, and the distance changes based on latitude.
    """
    earth_radius = 6378137  # Earth's radius in meters (WGS84)
    # Longitude distance decreases as you move towards the poles
    return (math.pi / 180) * earth_radius * math.cos(math.radians(latitude))

# Function to generate a grid of coordinates within a bounding box
def generate_geo_grid(min_lat, max_lat, min_lon, max_lon, step_meters):
    """
    Generate a grid of geographical coordinates within a bounding box defined by min_lat, max_lat, min_lon, max_lon
    with a specific step in meters (step_meters).
    
    :param min_lat: Minimum latitude of the bounding box
    :param max_lat: Maximum latitude of the bounding box
    :param min_lon: Minimum longitude of the bounding box
    :param max_lon: Maximum longitude of the bounding box
    :param step_meters: Step size in meters for the grid
    :return: GeoDataFrame containing Point geometries for the grid coordinates
    """
    # Convert step in meters to step in degrees for latitude
    degrees_per_meter_lat = 1 / 111320  # Approximate meters per degree latitude
    step_deg_lat = step_meters * degrees_per_meter_lat

    # List to store the coordinates
    coordinates = []
    
    # Start from min_lat and iterate until max_lat
    latitudes = []
    lats = min_lat
    while lats <= max_lat:
        latitudes.append(lats)
        lats += step_deg_lat

    # For each latitude, calculate the step in degrees for longitude
    for lat in latitudes:
        meters_per_deg_lon = meters_per_degree_longitude(lat)
        step_deg_lon = step_meters / meters_per_deg_lon
        
        # Generate longitudes for the current latitude
        lons = min_lon
        while lons <= max_lon:
            coordinates.append((lat, lons))
            lons += step_deg_lon
    
    # Convert coordinates to shapely Point geometries
    points = [Point(lon, lat) for lat, lon in coordinates]
    
    # Create a GeoDataFrame
    gdf = gpd.GeoDataFrame(geometry=points)
    
    return gdf


#%%

data_folder = ''

site = 'urse'
local_grid = f'{folder}cerra_grid_{site}.nc'








#%%
# Example usage
min_lat = 37.0  # Minimum latitude of the area (e.g., San Francisco)
max_lat = 38.0  # Maximum latitude of the area
min_lon = -123.0  # Minimum longitude of the area
max_lon = -122.0  # Maximum longitude of the area
step_meters = 250  # Grid step size in meters

# Generate the geo grid and store it in a GeoDataFrame
gdf = generate_geo_grid(min_lat, max_lat, min_lon, max_lon, step_meters)

# Display the GeoDataFrame (first few rows)
print(gdf.head())

# Optionally save to a shapefile
# gdf.to_file("grid_coordinates.shp")
