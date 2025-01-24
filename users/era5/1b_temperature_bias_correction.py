# -*- coding: utf-8 -*-
"""
Created on Thu Jan 23 21:43:31 2025

@author: roquesc
"""

# Load the two files
import os
import pandas as pd
import matplotlib.pyplot as plt

# paths
era5_path = "//vert/CHYN_OBSERVATOIRE_POSCHIAVINO/_Alps/_public_database/_climate/era5/_hourly/urse"
observed_path = "//vert/CHYN_OBSERVATOIRE_POSCHIAVINO/_Alps/_waterwise_database/_time_series/_deployment_sites/_urse/_climate/_air_temperature/_observation/_RG"

# File names
era5_name = '2m_temperature.csv'
observed_name = 'T.degC.csv'

# File paths
era5_file = os.path.join(era5_path, era5_name)
observed_file = os.path.join(observed_path, observed_name)

#%%

# Load and process ERA5 data
era5_data = pd.read_csv(era5_file)
era5_data['Date'] = pd.to_datetime(era5_data['datetime'], errors='coerce')  # Ensure 'Date' is datetime
era5_data['Temperature_C'] = era5_data['mean'] - 273.15  # Convert Kelvin to Celsius
era5_data = era5_data[['Date', 'Temperature_C']]  # Keep only relevant columns
era5_data = era5_data.resample('D', on='Date').mean().reset_index()  # Resample to weekly mean
# era5_data = era5_data.sort_values(by='Date')  # Ensure chronological order

# Load and process observed data
observed_data = pd.read_csv(observed_file, sep=';')  # Assuming semicolon-separated values
observed_data.columns = ['Date', 'Temperature_C']  # Rename columns
observed_data['Date'] = pd.to_datetime(observed_data['Date'], errors='coerce')  # Ensure 'Date' is datetime
observed_data = observed_data.resample('D', on='Date').mean().reset_index()  # Resample to weekly mean
observed_data = observed_data.sort_values(by='Date')  # Ensure chronological order

# Merge the datasets on the 'Date' column, keeping only overlapping dates
merged_data = pd.merge(era5_data, observed_data, on='Date', suffixes=('_ERA5', '_Obs'))

# Compute bias correction for the entire ERA5 dataset
mean_bias = era5_data['Temperature_C'].mean() - observed_data['Temperature_C'].mean()

# Apply bias correction to the entire ERA5 dataset
era5_data['Temperature_C_Corrected'] = era5_data['Temperature_C'] - mean_bias

# Merge corrected ERA5 data with observed data for validation
corrected_merged_data = pd.merge(
    era5_data[['Date', 'Temperature_C_Corrected']],  # Select corrected ERA5 columns
    observed_data[['Date', 'Temperature_C']],  # Select observed columns
    on='Date',
    suffixes=('_Corrected', '_Obs')
)

# Compute uncertainties (standard deviation of residuals)
residuals = corrected_merged_data['Temperature_C'] - corrected_merged_data['Temperature_C_Corrected']
uncertainty_std = residuals.std()
corrected_merged_data['Uncertainty_Lower'] = corrected_merged_data['Temperature_C_Corrected'] - 1.96 * uncertainty_std
corrected_merged_data['Uncertainty_Upper'] = corrected_merged_data['Temperature_C_Corrected'] + 1.96 * uncertainty_std

# Visualization: Time Series
plt.figure(figsize=(12, 6))
plt.plot(corrected_merged_data['Date'], corrected_merged_data['Temperature_C'], label='Observed Temperature', color='blue')
plt.plot(merged_data['Date'], merged_data['Temperature_C_ERA5'], label='ERA5 Temperature (Original)', color='red')
plt.plot(corrected_merged_data['Date'], corrected_merged_data['Temperature_C_Corrected'], label='ERA5 Temperature (Corrected)', color='green')
plt.fill_between(
    corrected_merged_data['Date'],
    corrected_merged_data['Uncertainty_Lower'],
    corrected_merged_data['Uncertainty_Upper'],
    color='green',
    alpha=0.2,
    label='Uncertainty Bounds (95%)'
)
plt.legend()
plt.title('Temperature Comparison and Bias Correction')
plt.xlabel('Date')
plt.ylabel('Temperature (°C)')
plt.grid()
plt.tight_layout()
plt.show()

# Residuals plot
plt.figure(figsize=(10, 5))
plt.hist(residuals, bins=30, color='purple', alpha=0.7, edgecolor='black')
plt.axvline(x=0, color='black', linestyle='--', label='Zero Residual')
plt.title('Distribution of Residuals')
plt.xlabel('Residual (Observed - Corrected)')
plt.ylabel('Frequency')
plt.legend()
plt.grid()
plt.tight_layout()
plt.show()

# Scatter plot: Observed vs ERA5 (Original and Corrected)
plt.figure(figsize=(10, 6))
plt.scatter(merged_data['Temperature_C_ERA5'], merged_data['Temperature_C_Obs'], color='blue', alpha=0.6, label='Original ERA5')
plt.scatter(corrected_merged_data['Temperature_C_Corrected'], corrected_merged_data['Temperature_C'], color='green', alpha=0.6, label='Corrected ERA5')
plt.plot([merged_data['Temperature_C_Obs'].min(), merged_data['Temperature_C_Obs'].max()],
         [merged_data['Temperature_C_Obs'].min(), merged_data['Temperature_C_Obs'].max()],
         color='black', linestyle='--', label='1:1 Line')  # 1:1 line
plt.title('Observed vs ERA5 (Original and Corrected)')
plt.xlabel('ERA5 Temperature (°C)')
plt.ylabel('Observed Temperature (°C)')
plt.legend()
plt.grid()
plt.tight_layout()
plt.show()
