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

import geopandas as gpd
import rioxarray

import xarray as xr
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
        
    def load_data(self, standard=True):
        """
        Load the NetCDF data into an xarray dataset.
        """
        try:
            self.dataset = xr.open_dataset(self.file_path)
            self.dataset = self.dataset.rename({'valid_time':'time'})           
            print(f"Data loaded from {self.file_path}")
        except Exception as e:
            print(f"Error loading data: {e}")
    
    def display_timestep(self, variable_name, timestep_index=0):
        """
        Display a specific time step for a given variable from the NetCDF dataset.
        
        :param variable_name: Name of the variable to plot (e.g., 'temperature', 'u10', etc.)
        :param timestep_index: Index of the time step to display (default is 0, i.e., the first time step)
        """
        # Extract the variable data from the dataset
        variable_data = self.dataset[variable_name]
    
        # Select the data for the given time step
        time_step_data = variable_data.isel(time = timestep_index)
    
        # Plotting
        # Assuming the data is on a 2D grid with latitude and longitude
        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
        time_step_data.plot(cmap='viridis', add_colorbar=True)
    
        # Adding a title with the time step information
        time_label = self.dataset['time'].isel(time=timestep_index).values
        
        ax.set_title(f"{variable_name} at Time Step {timestep_index} ({str(time_label)})")
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
    
        plt.show()
        
        return ax

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
            self.dataset = xr.open_dataset(self.file_path)
            self.dataset = self.dataset.rename({'valid_time':'time'})
            if standard:
                self.to_standard()            
            print(f"Data loaded from {self.file_path}")
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
if __name__ == "__main__":
    
    # Define paths
    ## Path reanalysis data
    path_data = 'L:\_Alps\_public_database\_climate\era5\_hourly\\2m_temperature\\1980\\1.nc'
    ## Path catchement polygone
    # Define paths
    polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
    polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
    
    catch_name = '_urse'
    
    # Initialize the ERA5Data object with the NetCDF file path        
    era5_data = Era5data(path_data)    
    # Load data
    era5_data.load_data() 
    axis = era5_data.display_timestep('temperature_2m_C',0)

    # Load the polygon
    polygon = gpd.read_file(polygon_path)
    polygon = polygon.to_crs(epsg=4326)
    
    polygon.plot(color='red')
    

    





    













