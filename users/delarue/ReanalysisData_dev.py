# -*- coding: utf-8 -*-
"""
Class ReanalysisData

Manage climate reanalysis format

Created on Wed Jan 29 11:39:10 2025

@author: delarueo
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from math import *

import geopandas as gpd
import rioxarray

import xarray as xr

import cartopy.crs as ccrs
import cartopy
import cartopy.feature as cfeature

import rasterio
from rasterio.plot import show
import numpy as np
import matplotlib.contour as contour

import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from cartopy.mpl.gridliner import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.ticker import LongitudeLocator, LatitudeLocator
from matplotlib.ticker import MaxNLocator
#%%

def map_extent(region, buffer=0):
    """
    Returns the geographical extent for a given region. If the region is a GeoDataFrame, 
    a bounding box with an optional buffer is returned.

    Parameters:
    - region (str or gpd.GeoDataFrame): A predefined region name or a GeoDataFrame object.
    - buffer (float): A factor to extend the bounding box by, as a proportion of the region's extent.

    Returns:
    - list: [lon_min, lon_max, lat_min, lat_max] representing the extent.
    """
    
    if isinstance(region, str):
        if region == 'europe':
            # Extent covering a larger region for Europe
            extent = [-25, 45, 32, 72]
        elif region == 'alps':
            # Approximate bounding box for the Alps
            extent = [4, 17, 43, 49]
        else:
            raise ValueError(f"Region '{region}' is not supported.")
    elif isinstance(region, gpd.GeoDataFrame):
        # If region is a GeoDataFrame, calculate bounding box with optional buffer
        bounds = region.total_bounds  # [lon_min, lat_min, lon_max, lat_max]
        lon_min, lat_min, lon_max, lat_max = bounds
        
        # Calculate extent with the buffer applied
        lon_extent = lon_max - lon_min
        lat_extent = lat_max - lat_min
        
        extent = [
            floor(10*(lon_min - buffer * lon_extent))/10,
            ceil(10*(lon_max + buffer * lon_extent))/10,
            floor(10*(lat_min - buffer * lat_extent))/10,
            ceil(10*(lat_max + buffer * lat_extent))/10
        ]
            
    elif region:
        # If region is a GeoDataFrame, calculate bounding box with optional buffer
        bounds = region.total_bounds  # [lon_min, lat_min, lon_max, lat_max]
        lon_min, lat_min, lon_max, lat_max = bounds
        
        # Calculate extent with the buffer applied
        lon_extent = lon_max - lon_min
        lat_extent = lat_max - lat_min
        
        extent = [
            floor(4*(lon_min - buffer * lon_extent))/4,
            ceil(4*(lon_max + buffer * lon_extent))/4,
            floor(4*(lat_min - buffer * lat_extent))/4,
            ceil(4*(lat_max + buffer * lat_extent))/4
        ]
    

    else:
        raise ValueError("Invalid region: Expected a string or a GeoDataFrame.")
    
    return extent

#%%

class ReanalysisData:

    def __init__(self, file_path):
        """
        Initialize the ERA5Data class with a NetCDF file path.
        
        :param file_path: Path to the NetCDF file
        """
        self.file_path = file_path
        self.dataset = None
        self.variables = []
        self.total_bounds = [0,0,0,0] #[lon_min, lat_min, lon_max, lat_max]
        
    def load_data(self, standard=True):
        """
        Load the NetCDF data into an xarray dataset.
        """
        try:
            self.dataset = xr.open_dataset(self.file_path)
            self.dataset = self.dataset.rename({'valid_time':'time'})
            self.total_bounds = [self.dataset.coords['longitude'].min().values,
                                 self.dataset.coords['latitude'].min().values,
                                 self.dataset.coords['longitude'].max().values,
                                 self.dataset.coords['latitude'].max().values]
      
            print(f"Data loaded from {self.file_path}")
        except Exception as e:
            print(f"Error loading data: {e}")
                
            
    
    
    def display_timestep(self, variable_name, timestep_index = 0, title = '', focus = True, buffer = 0, pixel = False ):
        """
        Display a specific time step for a given variable from the NetCDF dataset.
        
        :param variable_name: Name of the variable to plot (e.g., 'temperature', 'u10', etc.)
        :param timestep_index: Index of the time step to display (default is 0, i.e., the first time step)
        """
        # Extract the variable data from the dataset
        variable_data = self.dataset[variable_name].isel(time = timestep_index)
        
        # Extract the time for the plot title (assuming 'time' variable exists in your dataset)
        time_label = variable_data.time.values
        # Convert to a human-readable format (e.g., using pandas if it's a numpy.datetime64 object)
        time_str = pd.to_datetime(time_label).strftime('%Y-%m-%d %H:%M:%S')
        
        # Plotting
        # Create the figure and axis with PlateCarree projection (latitude/longitude)
        fig = plt.figure(figsize=(10, 10),layout="constrained")
        axis = plt.axes(projection=ccrs.PlateCarree())

        # Add coastlines and gridlines
        axis.coastlines()
        axis.add_feature(cfeature.BORDERS, linestyle=':')
        
        # Define gridline settings (latitude and longitude intervals)
        # Add gridlines with customized arguments
        gridlines = axis.gridlines(
            draw_labels=True,          # Draw the labels (longitude/latitude)
            linewidth= 0               # Gridline width
            )
        
        # Set custom limits to focus around a catchment (e.g., lat/lon bounding box)
        # Example coordinates: [min_lon, max_lon, min_lat, max_lat]
        if isinstance(focus,bool):
            catchment_extent = map_extent(focus,  buffer)
        else:
            catchment_extent = map_extent(focus, buffer)
        axis.set_extent(catchment_extent, crs=ccrs.PlateCarree())

        # Plot the temperature data
        variable_data.plot(ax=axis, 
                 transform=ccrs.PlateCarree(),         
                 cbar_kwargs={'shrink': 0.3,
                              'label': f'{variable_name}',
                              'extend': 'both'})
       
        # Plot pixel centers
        if pixel:
            lon, lat = np.meshgrid(self.dataset.longitude.values, self.dataset.latitude.values)
    
            # Flatten the meshgrid to 1D arrays for plotting
            x_pixels = lon.flatten()
            y_pixels = lat.flatten()
    
            axis.plot(x_pixels,y_pixels,'+k', transform=ccrs.PlateCarree())
        
        
        if isinstance(focus,gpd.GeoDataFrame):
            focus.plot(ax=axis,color='yellow', alpha=1, linewidth=2)       
                
        # Add figure title
        if title == '':
            title = f"{variable_name} ({time_str})"
            
        axis.set_title(title)
        
        plt.show()        
        return axis
    
    def close(self):
            """
            Close the dataset when done.
            """
            if self.dataset is not None:
                self.dataset.close()
                print("Dataset closed.")
            else:
                print("No dataset to close.")
    
 
    
class Era5data(ReanalysisData):
    
    STANDARD_CONVERSIONS = {
        't2m': lambda x: x - 273.15
        }
    STANDARD_VARIABLES = {
        't2m': 'temperature_2m_C'
        }
    
    def load_data(self, standard=True):
        """
        Load the NetCDF data into an xarray dataset.
        """
        try:
            if self.file_path[-3:] == '.nc':
                self.dataset = xr.open_dataset(self.file_path,engine='netcdf4')
                self.dataset = self.dataset.rename({'valid_time':'time'})
                self.total_bounds = [self.dataset.coords['longitude'].min().values,
                                     self.dataset.coords['latitude'].min().values,
                                     self.dataset.coords['longitude'].max().values,
                                     self.dataset.coords['latitude'].max().values]
                print(f"Data loaded from {self.file_path}")
                
            elif os.path.isdir(self.file_path):  # Check if the path is a directory
                # Get all netCDF files in the directory
                year_folders = [f'{self.file_path}{f}/' for f in os.listdir(self.file_path)]
                nc_files = [[f'{y}/{f}' for f in os.listdir(y) if f.endswith('.nc')] for y in year_folders]
                nc_files = [item for sublist in nc_files for item in sublist]

                if not nc_files:
                    print(f"No NetCDF files found in {self.file_path}")   
                dataset = xr.open_mfdataset(nc_files, engine='netcdf4', combine='by_coords')
                self.dataset = dataset
                self.dataset = self.dataset.rename({'valid_time':'time'})

                print(f"Data loaded from {len(nc_files)} CSV files in {self.file_path}")   
                
            # ERA raw to standard
            if standard:
                self.to_standard()  
            
        except Exception as e:
            print(f"Error loading data: {e}")
    

            
    def to_standard(self, verbose=False):
        """
        Apply necessary conversions and variable name changes
        to variables in the xarray dataset.
        Converts variables if needed (e.g., units conversion).
        
        :param dataset: The xarray dataset to process.
        :return: The modified xarray dataset.
        """
    
        # Iterate over each variable in the dataset
        for var_name in self.dataset.data_vars:
            if var_name in self.STANDARD_CONVERSIONS:
                # Apply the conversion if the variable has a corresponding function
                if verbose:
                    print(f"Applying conversion to {var_name}")
                conversion_func = self.STANDARD_CONVERSIONS[var_name]
                self.dataset[var_name] = conversion_func(self.dataset[var_name])
            if var_name in self.STANDARD_VARIABLES:
                # Apply the name changes if the variable has a standard name
                new_name = self.STANDARD_VARIABLES[var_name]
                if verbose:
                    print(f"Change variable name to {new_name}")                
                self.dataset = self.dataset.rename({var_name : new_name})
             
#%%
# Example usage:
# if __name__ == "__main__":
    
#     # ## Case open one file
#     # # Define paths
#     # path_data = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/1980/1.nc'
#     # # Initialize the ERA5Data object with the NetCDF file path        
#     # era5_data = Era5data(path_data)  
#     # era5_data.load_data()
#     # print(era5_data.dataset)
#     # # Define paths
#     # polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
#     # polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
    
#     # # Load the polygon
#     # polygon = gpd.read_file(polygon_path)
#     # polygon = polygon.to_crs(epsg=4326) 
    
#     # era5_data.display_timestep('temperature_2m_C', focus = polygon, buffer = 1)
    
#     # ## Case open all file in specfic folders
#     # path_data_2 = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/'
#     # era5_data_2 = Era5data(path_data_2)  
#     # era5_data_2.load_data()
#     # print(era5_data_2.dataset)
    
#     # era5_data_2.display_timestep('temperature_2m_C', focus='alps',pixel=True)
    
#     # era5_data_2.close()
    
    
#     # Dev extraction TimeSerie
#     # Define paths
#     path_data = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/1980/1.nc'
#     # Initialize the ERA5Data object with the NetCDF file path        
#     era5_data = Era5data(path_data)  
#     era5_data.load_data()
#     print('> DATA LOADED')
#     print(era5_data.dataset, end = '\n\n')    
       
#     pixel_data = era5_data.dataset.sel(latitude=46.25, longitude=10, method='nearest')
#     print('> EXTRACT PIXEL DATA') 
#     print(pixel_data, end = '\n\n')
    
#     pixel = Era5data('')
#     pixel.dataset = pixel_data
#     print('> DEFINE PIXEL') 
#     print(pixel.dataset, end = '\n\n')
    
#     pixel.display_timestep('temperature_2m_C', focus='alps',pixel=True)
    
    
#%%


#era5_data_2.display_timestep('temperature_2m_C')


# year_folders = [f'{path_data}{f}/' for f in os.listdir(path_data)]
# nc_files = [[f'{y}/{f}' for f in os.listdir(y) if f.endswith('.nc')] for y in year_folders]
# nc_files = [item for sublist in nc_files for item in sublist]
                          
# # print(nc_files)
                 
# dataset = xr.open_mfdataset(nc_files, engine='netcdf4', combine='by_coords')
# print(dataset)

#%%



# # Select data at the given latitude and longitude
# variable_data = dataset['t2m'].sel(latitude=46.25, longitude=10, method='nearest')
# fig = plt.figure(figsize=(10, 10),layout="constrained")
# axis = plt.axes()
# # Plot the time series
# variable_data.plot(ax=axis)


#%%
    ## Path catchement polygone
    
    # catch_name = '_urse'
    
    # # Initialize the ERA5Data object with the NetCDF file path        
    # era5_data = Era5data(path_data)    
    # # Load data
    # era5_data.load_data()
    # # Plot data 
    # era5_data.display_timestep('temperature_2m_C')
    
    # # Plot on top of Reanalysis data  
    # # Load the polygon
    # polygon = gpd.read_file(polygon_path)
    # polygon = polygon.to_crs(epsg=4326) 
    # era5_data.display_timestep('temperature_2m_C', focus = polygon, buffer = 5)

    
    # # polygon.plot(ax=ax,color='r',ls=)
    # polygon.plot()  
    # plt.show()
    
    
                # # Get all netCDF files in the directory
            # year_folders = [f'{path_data}{f}/' for f in os.listdir(path_data)]
            # nc_files = [[f'{y}/{f}' for f in os.listdir(y) if f.endswith('.nc')] for y in year_folders]
            # nc_files = [item for sublist in nc_files for item in sublist]
            
            # if not nc_files:
            #     print(f"No CSV files found in {self.file_path}")
            #     return
            
            # # Load all netCDF files and combine them into one xarray dataset
            # dataframes = []
            # for file in nc_files:
            #     full_path = os.path.join(self.file_path, file)
            #     datafile = xr.open_dataset(self.file_path)
            #     dataset.append(datafile)
            
            # # Concatenate all dataframes into one
            # dataset = pd.concat(dataset, ignore_index=True)
            
            # # Convert the combined dataframe to an xarray Dataset
            # self.dataset = xr.Dataset.from_dataframe(combined_df)
