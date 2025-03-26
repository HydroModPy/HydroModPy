# -*- coding: utf-8 -*-
"""
Created on Tue Feb 25 13:13:21 2025

@author: mathi
"""

from pyhelp_grid import PyhelpGrid
from pyhelp_era5 import PyhelpEra5

if __name__ == "__main__":
    folder = '.'
    base_file_path = f"{folder}/example/input_grid_base1.csv"
    csv_file_path = f"{folder}/example/input_grid_base2.csv"
    dem_file_path = f"{folder}/DEMs/ursa_RS3_rot0_250.tif"
    shp_file_path = f"{folder}/shps/watershed_corrected.shp" 
    reanalysis_folder_path = f"{folder}/_hourly3"
    
    

    pyhelp_grid = PyhelpGrid(base_file_path, csv_file_path, dem_file_path)
    pyhelp_grid.update_parameters(
    growth_start=100,  # Start of vegetation growth (day of year)
    growth_end=280,  # End of vegetation growth (day of year)
    wind=2.5,  # Average wind speed (m/s)
    hum1=60,  # Relative humidity in Winter (%)
    hum2=65,  # Relative humidity in Spring (%)
    hum3=70,  # Relative humidity in Summer (%)
    hum4=70,  # Relative humidity in Autumn (%)
    nlayer=1,  # Number of soil layers
    LAI=2.5,  # Leaf Area Index (m²/m²)
    EZD=15,  # Evaporative Zone Depth (cm)
    CN=70,  # Curve Number (Runoff Coefficient)
    lay_type1=1,  # Type of soil layer 1
    thick1=20,  # Thickness of soil layer 1 (cm)
    poro1=0.1,  # Porosity of soil layer 1 (vol/vol)
    fc1=0.28,  # Field capacity (vol/vol)
    wp1=0.12,  # Wilting point (vol/vol)
    ksat1=0.000008,  # Saturated hydraulic conductivity (m/day)
    dist_dr1=50,  # Drainage distance (m)
    slope1=35  # Terrain slope (%)
    )



    pyhelp_era5 = PyhelpEra5(era5_folder_path, shp_file_path)
    pyhelp_era5.extract_era5_daily_timeseries()


