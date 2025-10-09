# -*- coding: utf-8 -*-
"""
Created on Mon May  6 18:38:56 2024

@author: roquesc
"""

import os
import pandas as pd
import matplotlib.pyplot as plt

# Define the main directory containing all folders
main_directory = './_hourly/export'

# Define the directory to save the concatenated dataframe
output_directory = './sd'

# Create the output directory if it doesn't exist
if not os.path.exists(output_directory):
    os.makedirs(output_directory)

# Initialize an empty list to store dataframes
dfs = []

# Loop through each folder in the main directory
for folder in os.listdir(main_directory):
    folder_path = os.path.join(main_directory, folder)
    print(folder)
    
    # Check if it's a directory
    if os.path.isdir(folder_path):
        # Find the path to the tp.csv file in the current folder
        file_path = os.path.join(folder_path, 'sd.csv')
        
        # Check if the file exists
        if os.path.exists(file_path):
            # Read the CSV file as a dataframe
            df = pd.read_csv(file_path)
            
            # Convert 'time' column to datetime and set it as index
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)
            
            # Keep only the 'sd' variable in m
            df = df[['sd']]
            
          
            # Append the dataframe to the list
            dfs.append(df)

# Concatenate all dataframes into a single dataframe
concatenated_df = pd.concat(dfs)

# Sort the concatenated dataframe by time
concatenated_df.sort_index(inplace=True)

# Plot the dataframe
concatenated_df.plot(figsize=(10, 6))
plt.title('Hourly data ERA5')
plt.xlabel('Time')
plt.ylabel('snow depth [m]')
plt.grid(True)
plt.tight_layout()
plot_file_path = os.path.join(output_directory, 'sd_hourly.png')
plt.savefig(plot_file_path)

plt.show()
plt.show()

# Save the concatenated dataframe to a CSV file
output_file_path = os.path.join(output_directory, 'sd_hourly.csv')
concatenated_df.to_csv(output_file_path)

# Compute annual mean snow_depth
annual_mean_snow_depth = concatenated_df.groupby(concatenated_df.index.year).mean()


# Save the annual mean snow_depth to a CSV file
annual_mean_snow_depth_file_path = os.path.join(output_directory, 'sd_annual_mean.csv')
annual_mean_snow_depth.to_csv(annual_mean_snow_depth_file_path)

# Plot the dataframe
annual_mean_snow_depth.plot(figsize=(10, 6))
plt.title('Annual mean')
plt.xlabel('Time')
plt.ylabel('snow depth [m]')
plt.grid(True)
plt.tight_layout()
plot_file_path = os.path.join(output_directory, 'sd_annual_mean.png')
plt.savefig(plot_file_path)
plt.show()

# Compute monthly mean snow_depth
monthly_mean_snow_depth = concatenated_df.resample('M').mean()

# Save the annual mean snow_depth to a CSV file
monthly_mean_snow_depth_file_path = os.path.join(output_directory, 'sd_monthly_mean.csv')
monthly_mean_snow_depth.to_csv(monthly_mean_snow_depth_file_path)

# Plot the dataframe
monthly_mean_snow_depth.plot(figsize=(10, 6))
plt.title('Monthly mean')
plt.xlabel('Time')
plt.ylabel('snow depth [m]')
plt.grid(True)
plt.tight_layout()
plot_file_path = os.path.join(output_directory, 'sd_monthly_mean.png')
plt.savefig(plot_file_path)
plt.show()

print("CSV files saved successfully!")