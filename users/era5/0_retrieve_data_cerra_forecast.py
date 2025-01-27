# -*- coding: utf-8 -*-
"""
created by: Clément on Tue Nov  5 12:01:20 2024
reviewed by: 
    
https://medium.com/@nikola.gersak/analysing-climate-data-with-pythons-xarray-and-cordex-data-dc04428739fb    
    
"""
import os
import csv
import numpy as np
from datetime import date
import cdsapi
import time
import warnings
warnings.filterwarnings("ignore")

main_folder = "F:/_projects/_current/_alps/_cerra_forecast"
os.makedirs(main_folder, exist_ok=True)

# Initialize log file for failures
failure_log_file = os.path.join(main_folder, "failed_requests_log.csv")
if not os.path.exists(failure_log_file):
    with open(failure_log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Variable", "Year", "Month", "Error"])

# Current date for run identification
today = date.today().strftime("%b-%d-%Y")
print(f"\nRUN at\nnow = {today}\n")

# Variables and settings
possible_variable = [
        "10m_wind_direction",
        "10m_wind_gust_since_previous_post_processing",
        "10m_wind_speed",
        "2m_relative_humidity",
        "2m_temperature",
        "albedo",
        "evaporation",
        "high_cloud_cover",
        "low_cloud_cover",
        "maximum_2m_temperature_since_previous_post_processing",
        "mean_sea_level_pressure",
        "medium_cloud_cover",
        "minimum_2m_temperature_since_previous_post_processing",
        "momentum_flux_at_the_surface_u_component",
        "momentum_flux_at_the_surface_v_component",
        "skin_temperature",
        "snow_density",
        "snow_depth",
        "snow_depth_water_equivalent",
        "snow_fall_water_equivalent",
        "surface_latent_heat_flux",
        "surface_net_solar_radiation",
        "surface_net_solar_radiation_clear_sky",
        "surface_net_thermal_radiation",
        "surface_net_thermal_radiation_clear_sky",
        "surface_pressure",
        "surface_roughness",
        "surface_sensible_heat_flux",
        "surface_solar_radiation_downwards",
        "surface_thermal_radiation_downwards",
        "time_integrated_surface_direct_short_wave_radiation_flux",
        "total_cloud_cover",
        "total_column_integrated_water_vapour",
        "total_precipitation"
    ]


selected_variables = [
    '2m_temperature', 
    '2m_relative_humidity', 
    'albedo', 
    'evaporation',
    'snow_depth', 
    'snow_depth_water_equivalent', 
    'total_precipitation',
    'surface_net_solar_radiation']

start = 1985
stop = 2022
years = np.linspace(start, stop, stop - start + 1).astype(int)
months = np.linspace(1, 12, 12).astype(int)

# # years = 2022
# # months = np.linspace(1, 12, 12).astype(int)
# months = 11
# # years = np.array([years]).astype(int)
# months = np.array([months]).astype(int)

#%%

client = cdsapi.Client()

for v in selected_variables:
    variable_to_retrieve = str(v)
    print('#########################')
    print(f"I am retrieving variable: {variable_to_retrieve}\n")
    
    for y in years:
        year_to_retrieve = str(y)

        for m in months:
            month_to_retrieve = str(m)
            print(f"**Year {year_to_retrieve}\n**Month {month_to_retrieve}\n")
            
            folder_to_save = os.path.join(main_folder, today, variable_to_retrieve, year_to_retrieve)
            os.makedirs(folder_to_save, exist_ok=True)
            
            name_to_save = os.path.join(folder_to_save, f"{month_to_retrieve}.nc")
            start_time = time.time()
            dataset = "reanalysis-cerra-single-levels"
            request = {
                "level_type": "surface_or_atmosphere",
                "data_type": ["reanalysis"],
                "product_type": "forecast",
                "variable": variable_to_retrieve,
                "year": year_to_retrieve,
                "month": month_to_retrieve,
                "day": [f"{day:02d}" for day in range(1, 32)],
                "time": [
                    "00:00", "03:00", "06:00",
                    "09:00", "12:00", "15:00",
                    "18:00", "21:00"
                ],
                "leadtime_hour": ["6"],
                "data_format": "netcdf",
            }
            
            try:
                client.retrieve(dataset, request, name_to_save)
                end_time = time.time()
                duration = end_time - start_time
                print(f"Time taken for {variable_to_retrieve} for {year_to_retrieve}-{month_to_retrieve}: {duration:.2f} seconds\n")
            except Exception as e:
                error_message = str(e)
                print(f"Failed to download {variable_to_retrieve} for {year_to_retrieve}-{month_to_retrieve}: {error_message}\n")
                
                # Log the failure
                with open(failure_log_file, mode='a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow([variable_to_retrieve, year_to_retrieve, month_to_retrieve, error_message])
                continue
            print('#########################')
