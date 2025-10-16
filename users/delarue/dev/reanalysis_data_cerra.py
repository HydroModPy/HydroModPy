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
import math as m

import geopandas as gpd
from shapely.geometry import Polygon

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

import netCDF4
#%% Functions

def map_extent(region, buffer=0):
    """
    Returns the geographical extent for a given region. If the region is a GeoDataFrame, 
    a bounding box with an optional buffer is returned.

    Parameters:
    - region (str or gpd.GeoDataFrame): A predefined region name or a GeoDataFrame object.
    - buffer (float): A factor to extend the bounding box by, as a proportion of the region's extent.

    Returns:
        TODO: to lat long (traditional order)
    - list: [lon_min, lon_max, lat_min, lat_max] representing the extent.
    """
    
    if isinstance(region, str):
        if region == 'europe':
            # Extent covering a larger region for Europe
            extent = [-25, 45, 32, 72]
        elif region == 'alps':
            # Approximate bounding box for the Alps
            extent = [4, 17.5, 43, 49]
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
            m.floor(10*(lon_min - buffer * lon_extent))/10,
            m.ceil(10*(lon_max + buffer * lon_extent))/10,
            m.floor(10*(lat_min - buffer * lat_extent))/10,
            m.ceil(10*(lat_max + buffer * lat_extent))/10
        ]
    elif isinstance(region, list):
            extent = region
            
    elif region:
        # If region is a GeoDataFrame, calculate bounding box with optional buffer
        bounds = region.total_bounds  # [lon_min, lat_min, lon_max, lat_max]
        lon_min, lat_min, lon_max, lat_max = bounds
        
        # Calculate extent with the buffer applied
        lon_extent = lon_max - lon_min
        lat_extent = lat_max - lat_min
        
        extent = [
            m.floor(4*(lon_min - buffer * lon_extent))/4,
            m.ceil(4*(lon_max + buffer * lon_extent))/4,
            m.floor(4*(lat_min - buffer * lat_extent))/4,
            m.ceil(4*(lat_max + buffer * lat_extent))/4
        ]
    

    else:
        raise ValueError("Invalid region: Expected a string or a GeoDataFrame.")
    
    return extent

#%% Reanalysis class
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
      
            print(f">>Reanalysis: data loaded from {self.file_path}")
        except Exception as e:
            print(f">>Reanalysis: error loading data: {e}")
                
    def update_bounds(self):          
        try:
            self.total_bounds = [self.dataset.coords['longitude'].min().values,
                                 self.dataset.coords['latitude'].min().values,
                                 self.dataset.coords['longitude'].max().values,
                                 self.dataset.coords['latitude'].max().values]
      
            print(f">>Reanalysis: data loaded from {self.file_path}")
        except Exception as e:
            print(f">>Reanalysis: error loading data: {e}")
    
    def display_timestep(self, variable_name, timestep_index = 0, title = '', 
                         focus = True, buffer = 0, pixel = False ):
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
        # TODO: change ticks (0.25°)
        gridlines = axis.gridlines(
            draw_labels=True,          # Draw the labels (longitude/latitude)
            linewidth= 0.1               # Gridline width
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
    
    def extract_TimeSerie(self,lat,lon,variable,display = True):
        # TODO: to code 
        data = self.dataset[variable].sel(latitude=lat, longitude=lon)
        if display:
            fig,axis = plt.subplots(1,1,figsize=(10, 10),layout="constrained")
            data.plot(ax = axis)  
            axis.set_xlabel('time')
            axis.set_ylabel(variable)
            axis.set_title(variable)            
        return data
    
    def close(self):
            """
            Close the dataset when done.
            """
            if self.dataset is not None:
                self.dataset.close()
                print(">>Reanalysis: dataset closed.")
            else:
                print(">>Reanalysis: no dataset to close.")
    
 
#%% ERA5 data classe  
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
                print(f">>era5: Data loaded from {self.file_path}")
                
            elif os.path.isdir(self.file_path):  # Check if the path is a directory
                # Get all netCDF files in the directory
                year_folders = [f'{self.file_path}{f}/' for f in os.listdir(self.file_path)]
                nc_files = [[f'{y}/{f}' for f in os.listdir(y) if f.endswith('.nc')] for y in year_folders]
                nc_files = [item for sublist in nc_files for item in sublist]

                if not nc_files:
                    print(f">>era5: no NetCDF files found in {self.file_path}")   
                dataset = xr.open_mfdataset(nc_files, engine='netcdf4', combine='by_coords')
                self.dataset = dataset
                self.dataset = self.dataset.rename({'valid_time':'time'})

                print(f">>era5: data loaded from {len(nc_files)} CSV files in {self.file_path}")   
                
            # ERA raw to standard
            if standard:
                self.to_standard()  
            
        except Exception as e:
            print(f">>era5: error loading data: {e}")
    

            
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
                    print(f">>era5: applying conversion to {var_name}")
                conversion_func = self.STANDARD_CONVERSIONS[var_name]
                self.dataset[var_name] = conversion_func(self.dataset[var_name])
            if var_name in self.STANDARD_VARIABLES:
                # Apply the name changes if the variable has a standard name
                new_name = self.STANDARD_VARIABLES[var_name]
                if verbose:
                    print(f">>era5: change variable name to {new_name}")                
                self.dataset = self.dataset.rename({var_name : new_name})
             
                
#%% CERRA data class

class CerraData(ReanalysisData):
    
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
                self.dataset = xr.open_dataset(self.file_path, engine='rasterio')
                self.dataset = self.dataset.rename({'valid_time':'time'})
                
                
                lon = self.dataset['longitude'].where(
                                                self.dataset['longitude'] <= 180, 
                                                self.dataset['longitude'] -  360)
                lat = self.dataset['latitude']
                
                self.dataset.drop_coords(['latitude', 'longitude'], inplace=True)
                self.dataset['latitude'] = lat
                self.dataset['longitude'] = lon              
                
                self.total_bounds =  [20,17,65,35]
                # self.total_bounds = [self.dataset.coords['longitude'].min().values,
                #                      self.dataset.coords['latitude'].min().values,
                #                      self.dataset.coords['longitude'].max().values,
                #                      self.dataset.coords['latitude'].max().values]
                
                
                print(f">>cerra: data loaded from {self.file_path}")
                
            elif os.path.isdir(self.file_path):  # Check if the path is a directory
                # Get all netCDF files in the directory
                year_folders = [f'{self.file_path}{f}/' for f in os.listdir(self.file_path)]
                nc_files = [[f'{y}/{f}' for f in os.listdir(y) if f.endswith('.nc')] for y in year_folders]
                nc_files = [item for sublist in nc_files for item in sublist]

                if not nc_files:
                    print(f">>cerra: no NetCDF files found in {self.file_path}")   
                dataset = xr.open_mfdataset(nc_files, engine='netcdf4', combine='by_coords')
                self.dataset = dataset
                self.dataset = self.dataset.rename({'valid_time':'time'})

                print(f">>cerra: data loaded from {len(nc_files)} CSV files in {self.file_path}")   
                
            # CERRA raw to standard
            if standard:
                self.to_standard()  
            
        except Exception as e:
            print(f">>cerra: error loading data: {e}")
            
            
    def cut_step(self, timestep_index = [0,10], label = 'timestep', 
                  save = True, output = True, verbose = True):
        """
        
        Parameters
        ----------
        timestep_index : TYPE, optional
            DESCRIPTION. The default is 0.
        label : TYPE, optional
            DESCRIPTION. The default is 'timestep'.
        save : TYPE, optional
            DESCRIPTION. The default is True.
        output : TYPE, optional
            DESCRIPTION. The default is True.
            [True, False,'reset','close_all']

        Returns
        -------
        None.

        """
        if verbose:
            print('>>cerra: start cut_1step')
        data_ts = self.dataset.isel(time = timestep_index)
        print(data_ts)
        if save:
            
            if isinstance(save,bool):
                folder = self.file_path[:-7]
                year = self.file_path[-7:-3]
                print(folder)
                new_file_path = f'{folder}{year}_{label}.nc'
                
            elif isinstance(save,str):
                if os.path.isdir(save):
                    year = self.file_path[-7:-3]
                    new_file_path = f'{save}{year}_{label}.nc'
            else:
                new_file_path = f'./{year}_{label}.nc'
                print('>>cerra: invalid save location\n>>>>>>>> data saved in the current folder')
                
            if verbose :
                info = f'>>cerra: data saved at {new_file_path}'
                print(info) 
                
            data_ts.to_netcdf(new_file_path)
            
            if output:
                if verbose :
                    info = f'>>cerra: output process - {output}'
                    print(info) 
                    
                if output == True:
                    return data_ts
                    
                elif output == 'reset':
                    self.close()
                    self.file_path = new_file_path
                    self.load_data()
                    del data_ts                   
                
                elif output == 'close_all':
                    self.close()
                    del data_ts
                    del self
            
        else:
            return data_ts

        

        
    
    def crop_dataset(self, crop_coords = 'alps', label = 'crop',
                     save = True, inplace = True, verbose = False):
        """
        Parameters
        ----------
        crop_coords : TYPE, optional 
            if list coords [lat_min, lat_max, lon_min, lon_max]
            if string in [alps, europe]
            DESCRIPTION. The default is 'alps'.

        Returns
        -------
        None.

        """
        
        # Define the area to keep
        if isinstance(crop_coords, list):
            [lat_min, lat_max, lon_min, lon_max] = crop_coords 

            mask = np.zeros([1069,1069])
            # Assuming data.latitude and data.longitude are 2D arrays (1069 x 1069)
            latitudes = self.dataset.latitude.values
            longitudes = self.dataset.longitude.values

            # Create mask based on the latitudes and longitudes in one step using vectorized conditions
            mask = ((lat_min < latitudes) & (latitudes < lat_max) &
                    (lon_min < longitudes) & (longitudes < lon_max)).astype(int)

            self.dataset['alps_mask'] = (('y', 'x'), mask)
            self.dataset = self.dataset.where(self.dataset.alps_mask == 1)
            self.dataset = self.dataset.dropna("y", how="all").dropna("x", how="all")

        elif isinstance(crop_coords, str):
            if crop_coords == 'alps':
                mask = np.zeros([1069,1069])

                mask[390:521,475:675] = 1

                if label == 'crop':
                    label = 'alps'
        else:
            print('>>cerra: provided crop_coords not valid')
            return 0
        
        self.dataset['alps_mask'] = (('y', 'x'), mask)
        
        # Apply mask
        if inplace:            
            self.dataset = self.dataset.where(self.dataset.alps_mask == 1)
            self.dataset = self.dataset.dropna("y", how="all").dropna("x", how="all")
            if save: 
                if isinstance(save,bool):
                    folder = self.file_path[:-7]
                    year = self.file_path[-7:-3]
                    print(folder)
                    new_file_path = f'{folder}{year}_{label}.nc'
                    
                elif isinstance(save,str):
                    if os.path.isdir(save):
                        year = self.file_path[-7:-3]
                        new_file_path = f'{save}{year}_{label}.nc'
                else:
                    new_file_path = f'./{year}_{label}.nc'
                    print('>>cerra: invalid save location\n>>>>>>>> data saved in the current folder')
                    
                self.dataset.to_netcdf(new_file_path)
                if verbose :
                    info = f'>>cerra: cropped data saved at {new_file_path}'
                    print(info)  
                
        else:
            new_data = CerraData()
            new_data.dataset = self.dataset.where(self.dataset.alps_mask == 1).dropna("y", how="all").dropna("x", how="all")
            new_data.dataset = new_data.dataset.dropna("y", how="all").dropna("x", how="all")
            # Save the cropped data into a new NetCDF file
            if save:
                if isinstance(save,bool):
                    folder = self.file_path[:-7]
                    year = self.file_path[-7:-3]
                    print(folder)
                    new_file_path = f'{folder}{year}_{label}.nc'
                    
                elif isinstance(save,str):
                    if os.path.isdir(save):
                        year = self.file_path[-7:-3]
                        new_file_path = f'{save}{year}_{label}.nc'
                else:
                    new_file_path = f'./{year}_{label}.nc'
                    print('>>cerra: invalid save location\n>>>>>>>> data saved in the current folder')
                    
                new_data.to_netcdf(new_file_path)   
                if verbose :
                    info = f'>>cerra: cropped data saved at {new_file_path}'
                    print(info)                
                
            return new_data
    
    
    

    def display_timestep(self, variable_name, timestep_index = 0, title = '', 
                          focus = True, buffer = 0, pixel = False ):
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
        background = True
        if background:
            axis.coastlines()
            axis.add_feature(cfeature.BORDERS, linestyle=':')
        
        # Define gridline settings (latitude and longitude intervals)
        # Add gridlines with customized arguments
        # TODO: change ticks (0.25°)
        # gridlines = axis.gridlines(
        #                 draw_labels=True,          # Draw the labels (longitude/latitude)
        #                 linewidth= 0.1               # Gridline width
        #                 )
        
        # Set custom limits to focus around a catchment (e.g., lat/lon bounding box)
        # Example coordinates: [min_lon, max_lon, min_lat, max_lat]
        if isinstance(focus,bool):
            catchment_extent = map_extent(focus, buffer)
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
    
    def to_standard(self, verbose=True):
        """
        Apply necessary conversions and variable name changes
        to variables in the xarray dataset.
        Converts variables if needed (e.g., units conversion).
        
        :param dataset: The xarray dataset to process.
        :return: The modified xarray dataset.
        """
        print('>>cerra: to standard')
        # Iterate over each variable in the dataset
        for var_name in self.dataset.data_vars:
            if var_name in self.STANDARD_CONVERSIONS:
                # Apply the conversion if the variable has a corresponding function                
                conversion_func = self.STANDARD_CONVERSIONS[var_name]
                self.dataset[var_name] = self.dataset[var_name] - 273.15
                # self.dataset[var_name] = conversion_func(self.dataset[var_name])
                if verbose:
                    print(f">>cerra: apply conversion to {var_name}")
            if var_name in self.STANDARD_VARIABLES:
                # Apply the name changes if the variable has a standard name
                new_name = self.STANDARD_VARIABLES[var_name]
                self.dataset = self.dataset.rename({var_name : new_name})
                if verbose:
                    print(f">>cerra: change variable name to {new_name}") 
             




#%% Example usage:
if __name__ == "__main__":

    # # command = input("Select an action ['load' 'display' 'plot' 'close' 'stop']:")

    # # Define path polygone
    # polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
    # polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
    # # Load the polygon
    # polygon = gpd.read_file(polygon_path)
    # polygon = polygon.to_crs(epsg=4326) 


    
    # ## Case open one file
    # year = 1984
    # # Define path data
    # path_data = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
    # # Initialize the object with the NetCDF file path        
    # data = CerraData(path_data) 
    # data.load_data()
    # print(data.dataset)
    
    # data.cut_step(timestep_index= range(10), output = 'reset')
    # print(data.dataset)
    
    
    # data.crop_dataset('alps')
    # plt.figure()
    # plt.plot(data.dataset.latitude)
    # plt.grid()
    # plt.show()
    # plt.figure()
    # plt.plot(data.dataset.longitude)
    # plt.grid()
    # plt.show()
    

#%% alps area 
    # Define the four corner coordinates (longitude, latitude)
    # These are for example purposes
    # # Bottom-left (lon_min, lat_min), top-left (lon_min, lat_max), top-right (lon_max, lat_max), bottom-right (lon_max, lat_min)
    # lat_min, lat_max = 43, 49
    # lon_min, lon_max =  4, 17.5
      
    # mask = np.zeros([1069,1069])
    # latitudes = data.dataset.latitude.values
    # longitudes = data.dataset.longitude.values
    # for Y in range(0,1069):
    #     for X in range(0,1069):
    #         lat = latitudes[X,Y]
    #         lon = longitudes[X,Y]
    #         test = (lat_min<lat and lat<lat_max and lon_min<lon and lon<lon_max)            
    #         if test:
    #             mask[X,Y] = 1    
                
    # layer = data.dataset['t2m'].isel(time=0)*mask

    # # # Apply the mask to the dataset
    # # masked_data = data.dataset.where(mask)
    
    # # # Optionally, drop rows/columns with NaNs if needed (for example)
    # # masked_data_clean = masked_data.dropna(dim="x", how="all").dropna(dim="y", how="all")
    
    # # Plot the mask to visualize
    # plt.imshow(layer, cmap='gray')
    # plt.title('Mask Visualization')
    # plt.colorbar(label='Mask Value (0 or 1)')
    # plt.ylim([350,550])
    # plt.xlim([450,700])
    
    
    
#%%   
    
    
    
    
    
#     mask = np.array([[((lat_min<=lat & lat<=lat_max) & (lon_min<=lon & lon<=lon_max)) for
#                       lat in 
#                       ]])

#     # Define the coordinates of the rectangle's corners
#     rectangle_coords = [
#         (lon_min, lat_min),  # Bottom-left
#         (lon_min, lat_max),  # Top-left
#         (lon_max, lat_max),  # Top-right
#         (lon_max, lat_min),  # Bottom-right
#         (lon_min, lat_min)   # Closing the polygon by returning to bottom-left
#     ]

#     # Create a Polygon geometry from the rectangle coordinates
#     rectangle = Polygon(rectangle_coords)
    
#     # Create a GeoDataFrame with the Polygon geometry
#     alps = gpd.GeoDataFrame(geometry=[rectangle])
    
#     # Set the projection (Coordinate Reference System) of the GeoDataFrame
#     # Assuming WGS 84 (EPSG:4326) for lat/lon coordinates
#     alps.set_crs('EPSG:4326', allow_override=True, inplace=True)
    
#     # Print the GeoDataFrame with the rectangle
#     print(alps)
    
#     ShapeMask = rasterio.features.geometry_mask(alps,
#                                       out_shape=(len(data.dataset.y), len(data.dataset.x)),
#                                       transform=ccrs.PlateCarree(),
#                                       invert=True)
#     ShapeMask = xr.DataArray(ShapeMask , dims=("y", "x"))
    
#     # Then apply the mask
#     NDVImasked = data.dataset.where(ShapeMask == True)

# #%% display close
    
#     data.display_timestep('t2m',focus = [0,1069,0,1069])              

#     data.close()

# # if __name__ == "__main__":
    
# #     example = True
# #     while example:
# #         command = input("Select an action ['load' 'display' 'plot' 'close' 'stop']:")
    
# #         # Define path polygone
# #         polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
# #         polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')    
# #         # Load the polygon
# #         polygon = gpd.read_file(polygon_path)
# #         polygon = polygon.to_crs(epsg=4326) 
        
# #         if command == 'load':
# #             year = input("Year [1984-2022]:")
# #             ## Case open one file
# #             # Define path data
# #             path_data = f'L:/_Alps/_public_database/_climate/cerra_forecast/2m_temperature/{year}/{year}.nc'
# #             # Initialize the object with the NetCDF file path        
# #             data = CerraData(path_data)  
# #             data.load_data()
# #         elif command == 'display':
# #             if data:
# #                 print(data.dataset)  
        
# #         elif command == 'plot':

# #             data.display_timestep('t2m',focus = [74,343,20,64])              

#             # data.display_timestep('temperature_2m_C', focus = polygon, buffer = 1)
#             # data.close()
            
#         # elif int(command) == 1:
#         #     ## Case open all file in specfic folders
#         #     path_data_2 = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/'
#         #     era5_data_2 = Era5data(path_data_2)  
#         #     era5_data_2.load_data()
#         #     print(era5_data_2.dataset)    
#         #     era5_data_2.display_timestep('temperature_2m_C', focus='alps',pixel=True)
            
            
#         # elif int(command) == 2:
#         #     era5_data_2.extract_TimeSerie(46, 10, 'temperature_2m_C')
        
#         elif command == 'close':
#             data.close()
            
#         elif command == 'stop':
#             example = False
            
#         else:
#             print('???')
    
    
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
