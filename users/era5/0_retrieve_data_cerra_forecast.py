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

main_folder = "D:/_try/"
os.makedirs(main_folder, exist_ok=True)

# Current date for run identification
today = date.today().strftime("%b-%d-%Y")
print(f"\nRUN at\nnow = {today}\n")

# Initialize log file for failures
name_log = "failed_requests_log_" + today + ".csv"
failure_log_file = os.path.join(main_folder, name_log)
if not os.path.exists(failure_log_file):
    with open(failure_log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Variable", "Year", "Error"])



# Variables and settings
possible_variable = [
        "10m_wind_direction",

    ]


selected_variables = [
    '10m_wind_speed'
]


# start = 1984
start = 1984
stop = 1986
years = np.linspace(start, stop, stop - start + 1).astype(int)


#%%

client = cdsapi.Client()

for v in selected_variables:
    variable_to_retrieve = str(v)
    print('#########################')
    print(f"I am retrieving variable: {variable_to_retrieve}\n")
    
    for y in years:
        year_to_retrieve = str(y)
        print(f"year: {year_to_retrieve}\n")
        folder_to_save = os.path.join(main_folder, today, variable_to_retrieve, year_to_retrieve)
        os.makedirs(folder_to_save, exist_ok=True)
        
        name_to_save = os.path.join(folder_to_save, f"{year_to_retrieve}.nc")
        start_time = time.time()
        dataset = "reanalysis-cerra-single-levels"
        request = {
            "level_type": "surface_or_atmosphere",
            "data_type": ["reanalysis"],
            "product_type": "forecast",
            "variable": variable_to_retrieve,
            "year": year_to_retrieve,
            "month": [
                "01"
            ],
            "day": [
                "01", "02", "03",
                "04"
            ],
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
            duration = (end_time - start_time)/60
            print(f"Time taken for {variable_to_retrieve} for {year_to_retrieve}: {duration:.2f} minutes\n")
        except Exception as e:
            error_message = str(e)
            print(f"Failed to download {variable_to_retrieve} for {year_to_retrieve}: {error_message}\n")
            
            # Log the failure
            with open(failure_log_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([variable_to_retrieve, year_to_retrieve, error_message])
            continue
        print('#########################')
