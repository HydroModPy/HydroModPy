# -*- coding: utf-8 -*-
"""
Created on Tue Mar  4 09:50:46 2025

@author: roquesc
"""

import os
import csv
import cdsapi
import time
import warnings
from datetime import date

# Current date for run identification
today = date.today().strftime("%b-%d-%Y")
print(f"\nRUN at\nnow = {today}\n")

# Define paths
main_folder = "F:/_projects/_current/_alps/_cerra_forecast"
log_file_path = os.path.join(main_folder, "failed_requests_log_Jan-31-2025.csv")

# Check if file exists
if not os.path.exists(log_file_path):
    print(f"Error: Log file not found at {log_file_path}")
    exit()

# Read the failed requests log manually
failed_requests = []

with open(log_file_path, mode='r', encoding='utf-8') as file:
    lines = file.readlines()

# Process each line, ignoring the header
for line in lines[1:]:  # Skip the first line (header)
    columns = line.split(",")  # Split by comma manually
    if len(columns) >= 2:  # Ensure there are at least two columns
        variable = columns[0].strip().strip('"')
        year = columns[1].strip().strip('"')
        failed_requests.append((variable, year))

print(f"Failed requests count: {len(failed_requests)}")
print(f"Sample failed requests: {failed_requests[:5]}")  # Print first 5 to verify


#%% Reattempt data retrieval
client = cdsapi.Client()

dataset = "reanalysis-cerra-single-levels"
for variable_to_retrieve, year_to_retrieve in failed_requests:
    print(f"Retrying: {variable_to_retrieve} for year {year_to_retrieve}")

    folder_to_save = os.path.join(main_folder, "retry", today, variable_to_retrieve, year_to_retrieve)
    os.makedirs(folder_to_save, exist_ok=True)

    name_to_save = os.path.join(folder_to_save, f"{year_to_retrieve}.nc")
    start_time = time.time()
    
    request = {
        "level_type": "surface_or_atmosphere",
        "data_type": ["reanalysis"],
        "product_type": "forecast",
        "variable": variable_to_retrieve,
        "year": year_to_retrieve,
        "month": [f"{m:02d}" for m in range(1, 13)],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"],
        "leadtime_hour": ["6"],
        "data_format": "netcdf",
    }

    try:
        client.retrieve(dataset, request, name_to_save)
        end_time = time.time()
        duration = (end_time - start_time) / 60
        print(f"Successfully retrieved {variable_to_retrieve} for {year_to_retrieve} in {duration:.2f} minutes.\n")
    except Exception as e:
        print(f"Retry failed for {variable_to_retrieve} for {year_to_retrieve}: {str(e)}\n")
