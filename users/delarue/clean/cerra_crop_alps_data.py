# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 15:39:36 2025

@author: delarueo

Code used to cut cerra data 
21-24 03 2025
"""

import os
import shutil
import time
import xarray as xr
import numpy as np

#%% Functions 
def create_buffer_folder(folder_path):
    """
    Creates a buffer folder if it doesn't already exist.

    Parameters:
    -----------
    folder_path : str
        Path to the folder where buffers will be stored.

    Returns:
    --------
    None
    """
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)


def process_and_save_buffer(var, year, buffer_folder, data, b_inf, b_sup):
    """
    Process the data in time slices and save the buffer files as netCDF.

    Parameters:
    -----------
    var : str
        Variable name (e.g., '2m_temperature', 'total_precipitation').
    year : int
        Year of the data.
    buffer_folder : str
        Path to the folder where buffer files will be saved.
    data : xarray.Dataset
        The dataset loaded from the input netCDF file.
    b_inf : list
        List of starting indices for each time slice buffer.
    b_sup : list
        List of ending indices for each time slice buffer.

    Returns:
    --------
    list
        List of file paths to the saved buffer files.
    """
    list_buffer_path = []
    for b in range(len(b_inf)):
        bi, bs = b_inf[b], b_sup[b]
        
        buffer = data.isel(valid_time=range(bi, bs))  # Extract the time slice for this buffer
        buffer['alps_mask'] = (('y', 'x'), mask)  # Apply mask
        buffer = buffer.where(buffer.alps_mask == 1)  # Apply the Alps mask
        buffer = buffer.dropna("y", how="all").dropna("x", how="all")  # Drop all-NaN rows/columns
        buffer = buffer.drop(['expver', 'alps_mask'])  # Drop unnecessary variables
        
        buffer_path = f'{buffer_folder}{b}.nc'
        buffer.to_netcdf(buffer_path, mode='w')  # Save buffer as netCDF file
        list_buffer_path.append(buffer_path)

    return list_buffer_path


def combine_buffers(list_buffer_path, alps_file_path):
    """
    Combines multiple buffer files into one netCDF file.

    Parameters:
    -----------
    list_buffer_path : list
        List of file paths to the individual buffer files.
    alps_file_path : str
        Path to save the combined netCDF file.

    Returns:
    --------
    None
    """
    # Combine the separated buffer files into one large dataset
    data = xr.open_dataset(list_buffer_path[0])
    for f in list_buffer_path[1:]:
        buffer = xr.open_dataset(f)
        data = xr.concat([data, buffer], dim='valid_time')

    data.to_netcdf(alps_file_path, mode='w')  # Save combined data
    data.close()  # Close the dataset


def clean_buffer_folder(buffer_folder):
    """
    Removes the buffer folder and all its contents.

    Parameters:
    -----------
    buffer_folder : str
        Path to the buffer folder to be removed.

    Returns:
    --------
    None
    """
    if os.path.exists(buffer_folder) and os.path.isdir(buffer_folder):
        shutil.rmtree(buffer_folder)  # Remove buffer folder and its contents




#%% Start time count
start = time.time()
end = start
print('> START\n')

#%% Data path and space to explore - TO COMPLITE
cerra_path = 'F:/_cerra_forecast/'
operation_path = 'C:/Users/delarueo/Desktop/crash_zone/'
missing_file = f'{cerra_path}missing.txt'

years = range(1984, 2025) #range(1984, 2023)
variables = ['2m_temperature',
            'total_precipitation', 'snow_depth',
            'surface_net_solar_radiation',
            'total_precipitation',
            'snow_depth_water_equivalent']

#%% Standard: masks & buffer size
mask = np.zeros([1069, 1069])
mask[390:521, 475:675] = 1

n_buffer = 100  # Number of time steps in a buffer (max 1000)


#%% Main loop for processing variables and years

verbose = False
if verbose: 
    vprint = (lambda x: print(x, end = '')) 
else:
    vprint = (lambda x: None)  


missing = 'missing data\n'    

for var in variables:  
    print(f'>> {var}\n>> ', end='')
    missing += f'{var}\n( '
    for year in years:
        print(f'{year} ', end='')
        
        # Define file paths
        var_path = f'{cerra_path}{var}/'
        file_path = f'{var_path}{year}/{year}.nc'
        alps_file_path = f'{var_path}{year}/{year}_alps.nc'
        
        local_file_path = f'{operation_path}buffer/{year}.nc'
        buffer_folder = f'{operation_path}buffer/'
        
        
        # Check if data available for given variable and year
        if os.path.isfile(file_path):
            
            # Create buffer folder if needed
            create_buffer_folder(buffer_folder)  
            
            # Create local copy and Open dataset
            vprint('\n>>> create data local copy\n')
            shutil.copy(file_path, local_file_path)
            
            vprint('>>> open local data file\n')            
            data = xr.open_dataset(local_file_path, mode='r', engine='netcdf4')
            
            n_ts = data.dims['valid_time']  # Total time steps
    
            # Define time step ranges for splitting
            b_inf = [i * n_buffer for i in range(n_ts // n_buffer + 1)]
            b_sup = [j for j in b_inf[1:]] + [n_ts]
    
            # Process and save the buffer files
            vprint('>>> crop & save buffers\n')
            list_buffer_path = process_and_save_buffer(var, year, buffer_folder, data, b_inf, b_sup)
            
            # Combine the separated buffer files
            vprint('>>> combine buffers\n')
            combine_buffers(list_buffer_path, alps_file_path)
            
            # Close the dataset
            data.close()
            
            # Clean buffer folder
            vprint('>>> clean Up\n')
            clean_buffer_folder(buffer_folder)
            # os.remove(local_file_path) 
            
            
        else:
            print('no data ', end='')
            missing += f'{year} '
    
    missing += ')\n'
    # Display time elapsed for this year
    step = end
    end = time.time()
    print(f'\n>> {end - step:.2f} s - {end - start:.2f} s\n', end = '')

#%% Final end message


tf = open(missing_file, "w")
tf.write(missing)
tf.close()

print('> END')
