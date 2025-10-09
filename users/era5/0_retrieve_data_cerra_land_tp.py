# -*- coding: utf-8 -*-
"""
created by: Clément on Tue Nov  5 12:01:20 2024
modified by: Odile - 10.06.2025
    
"""
import os
import csv
import numpy as np
from datetime import date
import cdsapi
import time
import warnings
warnings.filterwarnings("ignore")

#%%
main_folder = "M:/crash_zone/_cerra_land/"

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
# possible_variable = [
#         "10m_wind_direction",
#         "10m_wind_speed",
#         "2m_relative_humidity",
#         "2m_temperature",
#         "albedo",
#         "high_cloud_cover",
#         "land_sea_mask",
#         "low_cloud_cover",
#         "mean_sea_level_pressure",
#         "medium_cloud_cover",
#         "orography",
#         "skin_temperature",
#         "snow_density",
#         "snow_depth",
#         "snow_depth_water_equivalent",
#         "surface_pressure",
#         "surface_roughness",
#         "total_cloud_cover",
#         "total_column_integrated_water_vapour"
#     ],


selected_variables = ['total_precipitation']

start = 1984
stop = 2022
years = np.linspace(start, stop, stop - start + 1).astype(int)
months = np.linspace(1, 12, 12).astype(int)

#%%

client = cdsapi.Client({'url': 'https://cds.climate.copernicus.eu/api',
                        'key': 'd19868e7-e3f9-4b63-a8ec-c048f2a63d75'})

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
            dataset = "reanalysis-cerra-land"
            request = {
                "level_type": ["surface"],
                "product_type": ["analysis"],
                "variable": variable_to_retrieve,
                "year": year_to_retrieve,
                "month": month_to_retrieve,
                "day": [f"{day:02d}" for day in range(1, 32)],
                "time": ["06:00"],
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
