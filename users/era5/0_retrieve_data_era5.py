# -*- coding: utf-8 -*-
"""
created by: Clément on Tue Nov  5 12:01:20 2024
reviewed by: 
    
"""
import os
import csv
import numpy as np
from datetime import date
import cdsapi
import time

main_folder = "F:/_projects/_current/era5_alpine"

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
# possible_variables = ['2m_temperature', 'clear_sky_direct_solar_radiation_at_surface', 
#                       'snow_depth', 'surface_net_solar_radiation', 'total_column_snow_water', 
#                       'total_precipitation', 'forecast_albedo','evaporation', 'snow_evaporation']


# selected_variables = ['2m_temperature', 'total_precipitation', 'forecast_albedo', 'snow_depth', 'surface_net_solar_radiation']
selected_variables = ['2m_temperature']


start = 1980
stop = 2024
years = np.linspace(start, stop, stop - start + 1).astype(int)
# months = np.linspace(1, 12, 12).astype(int)

# # years = 2022
# # months = np.linspace(1, 12, 12).astype(int)
months = 11
# # years = np.array([years]).astype(int)
months = np.array([months]).astype(int)

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
            dataset = "reanalysis-era5-land" #https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview
            request = {
                "variable": variable_to_retrieve,
                "year": year_to_retrieve,
                "month": month_to_retrieve,
                "day": [f"{day:02d}" for day in range(1, 32)],
                "time": [f"{hour:02d}:00" for hour in range(24)],
                "data_format": "netcdf",
                "download_format": "unarchived",
                "area": [49, 4, 43, 17.5],  # Alpine space extent
                "grid": [0.25, 0.25],
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
