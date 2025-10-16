# -*- coding: utf-8 -*-
"""
Created on Tue Feb 25 13:13:21 2025

@author: mathi
"""

from pyhelp_grid import PyhelpGrid
from pyhelp_era5 import PyhelpEra5

if __name__ == "__main__":
    base_file_path = "C:/Users/mathi/Dev/pyhelp-master/pyhelp-test/example/example/input_grid_base.csv"
    csv_file_path = "C:/Users/mathi/Dev/pyhelp-master/pyhelp-test/example/example/input_grid_base1.csv"
    dem_file_path = "C:/Users/mathi/Dev/pyhelp-master/Poschiavo_Mathias/DEMs/ursa_RS3_rot0_250.tif"
    shp_file_path = "C:/Users/mathi/Dev/pyhelp-master/Poschiavo_Mathias/shps/watershed_corrected.shp" 
    era5_folder_path = "C:/Users/mathi/Dev/pyhelp-master/Poschiavo_Mathias/_hourly3"
    
    #pyhelp_era5 = PyhelpEra5(era5_folder_path)
    #pyhelp_era5.extract_era5_daily_timeseries()
    
    

    pyhelp_grid = PyhelpGrid(base_file_path, csv_file_path, dem_file_path, shp_file_path)

    pyhelp_grid.update_parameters(
    growth_start=120,  # Start of vegetation growth (day of year)
    growth_end=230,  # End of vegetation growth (day of year)
    wind=10,  # Average wind speed (m/s)
    hum1=60,  # Relative humidity in Winter (%)
    hum2=65,  # Relative humidity in Spring (%)
    hum3=70,  # Relative humidity in Summer (%)
    hum4=70,  # Relative humidity in Autumn (%)
    nlayer=1,  # Number of soil layers
    LAI=2.4,  # Leaf Area Index (m²/m²)
    EZD=44.5,  # Evaporative Zone Depth (cm)
    CN=55,  # Curve Number (Runoff Coefficient)
    lay_type1=1,  # Type of soil layer 1
    thick1=100,  # Thickness of soil layer 1 (cm)
    poro1=0.45,  # Porosity of soil layer 1 (vol/vol)
    fc1=0.23,  # Field capacity (vol/vol)
    wp1=0.116,  # Wilting point (vol/vol)
    ksat1=0.00037,  # Saturated hydraulic conductivity (cm/s)
    dist_dr1=50,  # Drainage distance (m)
    slope1=35  # Terrain slope (%)
    )
    



