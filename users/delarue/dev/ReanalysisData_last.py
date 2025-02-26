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
        fig = plt.figure(figsize=(10, 6))
        time_step_data.plot(cmap='viridis', add_colorbar=True)
    
        # Adding a title with the time step information
        time_label = self.dataset['time'].isel(time=timestep_index).values
        plt.title(f"{variable_name} at Time Step {timestep_index} ({str(time_label)})")
        plt.xlabel('Longitude')
        plt.ylabel('Latitude')
    
        plt.show()
        
        return fig

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
             

# Example usage:
if __name__ == "__main__":
    
    # Define paths
    
    # Initialize the ERA5Data object with the NetCDF file path
    
    
    path_data = 'L:\_Alps\_public_database\_climate\era5\_hourly\\2m_temperature\\1980\\1.nc'    
    era5_data = Era5data(path_data)
    
    # Load data
    era5_data.load_data() 
    
    # # Check standard 
    # era5_data.load_data(standard=False)   
    # era5_data.display_timestep('t2m',0)  
    # era5_data.to_standard()
    # era5_data.display_timestep('temperature_2m_C',0) 
    


    # Define paths
    base_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
    polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'
    catch_name = '_urse'
    output_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_process\_climate\_era5'
    output_folder = os.path.join(output_folder,catch_name)
    #r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly\extract'
    polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
    # variables = 
    variables = ['total_precipitation']

    # Load the polygon
    polygon = gpd.read_file(polygon_path) 
    
    
    
    
    
    
    
    era5_data.close()
#%%
    
      
    
    
    # # Get the variable data (e.g., temperature, wind components, etc.)
    # temperature = era5_data.get_variable('temperature')
    # if temperature is not None:
    #     print(temperature)

    # # Get and print time, latitude, and longitude
    # time = era5_data.get_time()
    # latitude = era5_data.get_latitude()
    # longitude = era5_data.get_longitude()

    # print(f"Time: {time}")
    # print(f"Latitude: {latitude}")
    # print(f"Longitude: {longitude}")

    # # Plot a variable (e.g., temperature)
    # era5_data.plot_variable('temperature')

    # Close the dataset
    #  era5_data.close()





















# import os
# import geopandas as gpd
# import xarray as xr
# import rioxarray
 
# import pandas as pd
# import matplotlib.pyplot as plt


# import iris
# import matplotlib.pyplot as plt

# class ReanalysisData:

#     def __init__(self, file_path):
#         """
#         Initialize the ReanalysisData class with a NetCDF file path.
        
#         :param file_path: Path to the NetCDF file
#         """
#         self.file_path = file_path
#         self.cube = None
#         # self.variables = []

#     def load_data(self):
#         """
#         Load the NetCDF data into an Iris Cube.
#         """
#         try:
#             # Load the NetCDF file into an Iris Cube
#             self.cube = iris.load(self.file_path)
#             print(f"Data loaded from {self.file_path}")
#         except Exception as e:
#             print(f"Error loading data: {e}")

#     def display_timestep(self, variable_name, timestep_index=0):
#         """
#         Display a specific time step for a given variable from the NetCDF dataset.
        
#         :param variable_name: Name of the variable to plot (e.g., 'temperature', 'u10', etc.)
#         :param timestep_index: Index of the time step to display (default is 0, i.e., the first time step)
#         """
#         if self.cube is not None:
#             # Find the variable in the Cube by its name (assuming it's in the cube list)
#             matching_cubes = [c for c in self.cube if c.name() == variable_name]
#             if matching_cubes:
#                 # Get the first matching cube (variable)
#                 variable_cube = matching_cubes[0]
                
#                 # Select the specific time step using .slices()
#                 time_slices = variable_cube.slices(['time'])
#                 timestep_data = time_slices[timestep_index]
                
#                 # Plot the data (assuming it's 2D spatial data such as lat/lon grid)
#                 timestep_data.data.plot()
#                 plt.title(f"{variable_name} at time step {timestep_index}")
#                 plt.show()
#             else:
#                 print(f"Variable {variable_name} not found in the dataset.")
#         else:
#             print("Dataset not loaded yet.")

#     def close(self):
#         """
#         Close the dataset when done.
#         """
#         # Iris does not have a specific close method, as it is file-handling free
#         # But you can manually clear any resources if needed.
#         if self.cube is not None:
#             self.cube = None
#             print("Dataset closed.")
#         else:
#             print("No dataset to close.")

# #%% Example usage:
# if __name__ == "__main__":
#     # Initialize the ReanalysisData object with the NetCDF file path
#     path_data = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/1980/1.nc'
#     era5_data = ReanalysisData(path_data)
    
#     # Load data
#     era5_data.load_data()
    
#     print(era5_data.cube)
#     # # Display the variable at the first time step
#     # era5_data.display_timestep('t2m')
    
#     # # Close the dataset
#     # era5_data.close()


#%% version 1 with XARRAY
# import xarray as xr

# class ReanalysisData:

#     def __init__(self, file_path):
#         """
#         Initialize the ERA5Data class with a NetCDF file path.
        
#         :param file_path: Path to the NetCDF file
#         """
#         self.file_path = file_path
#         self.dataset = None
#         self.variables = []
        
#     def load_data(self):
#         """
#         Load the NetCDF data into an xarray dataset.
#         """
#         try:
#             self.dataset = xr.open_dataset(self.file_path)
#             print(f"Data loaded from {self.file_path}")
#         except Exception as e:
#             print(f"Error loading data: {e}")
    
#     def display_timestep(self, variable_name, timestep_index=0):
#         """
#         Display a specific time step for a given variable from the NetCDF dataset.
        
#         :param variable_name: Name of the variable to plot (e.g., 'temperature', 'u10', etc.)
#         :param timestep_index: Index of the time step to display (default is 0, i.e., the first time step)
#         """
#         if self.dataset is not None:
#             # Retrieve the variable data from the dataset
#             if variable_name in self.dataset:
#                 variable_data = self.dataset[variable_name]
                
#                 # Select the data for the specific time step
#                 timestep_data = variable_data.isel(time=self.dataset.valid_time[timestep_index])
                
#                 # Plot the data (assuming 2D spatial data such as lat/lon grid)
#                 timestep_data.plot()
#                 plt.title(f"{variable_name} at time step {timestep_index}")
#                 plt.show()
#             else:
#                 print(f"Variable {variable_name} not found in the dataset.")
#         else:
#             print("Dataset not loaded yet.")

#     def close(self):
#             """
#             Close the dataset when done.
#             """
#             if self.dataset is not None:
#                 self.dataset.close()
#                 print("Dataset closed.")
#             else:
#                 print("No dataset to close.")
    
# #%% Example usage:
# if __name__ == "__main__":
#     # Initialize the ERA5Data object with the NetCDF file path
#     path_data = 'L:\_Alps\_public_database\_climate\era5\_hourly\\2m_temperature\\1980\\1.nc'    
#     era5_data = ReanalysisData(path_data)
    
#     # Load data
#     era5_data.load_data()
#     print(era5_data.dataset.valid_time[0].value)
    
#     era5_data.display_timestep('t2m')
    
    
    
#     # # Get the variable data (e.g., temperature, wind components, etc.)
#     # temperature = era5_data.get_variable('temperature')
#     # if temperature is not None:
#     #     print(temperature)

#     # # Get and print time, latitude, and longitude
#     # time = era5_data.get_time()
#     # latitude = era5_data.get_latitude()
#     # longitude = era5_data.get_longitude()

#     # print(f"Time: {time}")
#     # print(f"Latitude: {latitude}")
#     # print(f"Longitude: {longitude}")

#     # # Plot a variable (e.g., temperature)
#     # era5_data.plot_variable('temperature')

#     # Close the dataset
#     #  era5_data.close()