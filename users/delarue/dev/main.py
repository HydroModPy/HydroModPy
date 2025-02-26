# -*- coding: utf-8 -*-
"""
Created on Fri Jan 31 16:27:21 2025

@author: delarueo
"""
from reanalysis_data import *
from time_serie import *

# Example usage:
if __name__ == "__main__":
    
    # ## Case open one file
    # # Define paths
    # path_data = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/1980/1.nc'
    # # Initialize the ERA5Data object with the NetCDF file path        
    # era5_data = Era5data(path_data)  
    # era5_data.load_data()
    # print(era5_data.dataset)
    # # Define paths
    # polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'    
    # polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
    
    # # Load the polygon
    # polygon = gpd.read_file(polygon_path)
    # polygon = polygon.to_crs(epsg=4326) 
    
    # era5_data.display_timestep('temperature_2m_C', focus = polygon, buffer = 1)
    
    # ## Case open all file in specfic folders
    # path_data_2 = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/'
    # era5_data_2 = Era5data(path_data_2)  
    # era5_data_2.load_data()
    # print(era5_data_2.dataset)
    
    # era5_data_2.display_timestep('temperature_2m_C', focus='alps',pixel=True)
    
    # era5_data_2.close()
    
    
    # Dev extraction TimeSerie
    # Define paths
    path_data = 'L:/_Alps/_public_database/_climate/era5/_hourly/2m_temperature/'
    # Initialize the ERA5Data object with the NetCDF file path        
    era5_data = Era5data(path_data)  
    era5_data.load_data()
    print('> DATA LOADED')
    print(era5_data.dataset, end = '\n\n')    
    era5_data.display_timestep('temperature_2m_C', timestep_index = -1, focus=[10,11,45,46])
       
    pixel_data = era5_data.dataset.sel(latitude=46.25, longitude=10, method='nearest')
    print('> EXTRACT PIXEL DATA') 
    print(pixel_data, end = '\n\n')
    
    # pixel = Era5data('')
    # pixel.dataset = pixel_data
    # print('> DEFINE PIXEL') 
    # print(pixel.dataset, end = '\n\n')
    