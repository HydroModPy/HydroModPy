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

# Example: Let's assume the dataset is already loaded as 'dataset'
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
# Find the nearest point in the South-West direction
nearest_lat, nearest_lon, idx, dist = find_nearest_point(dataset, lat_point, lon_point, direction="southwest")

print(f"The nearest point to the South-West is at latitude {nearest_lat}, longitude {nearest_lon}, with a distance of {dist}.")

# Create a polygon for visualization (can be any polygon)
polygon_coords = [(4.1, 45.3), (4.1, 45.0), (4.5, 45.0), (4.5, 45.3)]  # Example coordinates for a square polygon
polygon = Polygon(polygon_coords)

# Create a GeoDataFrame to hold the polygon
gdf = gpd.GeoDataFrame({'geometry': [polygon]}, crs="EPSG:4326")

# Create a point for the nearest point found
nearest_point = Point(nearest_lon, nearest_lat)

# Create a GeoDataFrame for the nearest point
point_gdf = gpd.GeoDataFrame({'geometry': [nearest_point]}, crs="EPSG:4326")

# Plot the polygon and the nearest point on the map
fig, ax = plt.subplots(figsize=(10, 10))

# Plot the polygon
gdf.plot(ax=ax, color='lightblue', edgecolor='black')

# Plot the nearest point
point_gdf.plot(ax=ax, color='red', marker='o', markersize=100, label = 'nearest point')

# Add the original point as well (for reference)
ax.plot(lon_point, lat_point, color='green', marker='+', markersize=10, label="Original Point")

# Plot all grid points (the entire grid)
grid_lat = dataset.lat.values
grid_lon = dataset.lon.values
ax.scatter(grid_lat, grid_lon, color='blue', s=5, label="Grid Points")

# Set axis labels
ax.set_xlabel('Longitude')
ax.set_ylabel('Latitude')

# Add title and legend
ax.set_title('Nearest Point Relative to Polygon')
ax.legend()

plt.show()
