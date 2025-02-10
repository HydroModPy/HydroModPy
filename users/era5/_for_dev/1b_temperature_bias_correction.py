# -*- coding: utf-8 -*-
"""
Created on Thu Jan 23 21:43:31 2025

@author: roquesc
"""

# Load the two files
import os
import pandas as pd
import matplotlib.pyplot as plt

plt.close('all')

# paths
catch_name = '_urse'
era5_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_process\_climate\_era5'
era5_path = os.path.join(era5_path,catch_name)

obs_station = '_RG'
observed_path = "//vert/CHYN_OBSERVATOIRE_POSCHIAVINO/_Alps/_waterwise_database/_time_series/_deployment_sites/_urse/_climate/_air_temperature/_observation"
observed_path = os.path.join(observed_path,obs_station)

# File names
era5_name = '2m_temperature.csv'
observed_name = 'T.degC.csv'

# File paths
era5_file = os.path.join(era5_path, era5_name)

observed_file = os.path.join(observed_path, observed_name)

#%% Load and process ERA5 data
era5_data = (
    pd.read_csv(era5_file)
    .assign(
        Date=lambda df: pd.to_datetime(df['datetime'], errors='coerce'),
        Temperature_C=lambda df: df['mean'] - 273.15  # Convert Kelvin to Celsius
    )
    .loc[:, ['Date', 'Temperature_C']]  # Keep only relevant columns
    .dropna(subset=['Date', 'Temperature_C'])  # Remove rows with NaN
    .set_index('Date')
    .sort_index()
    .resample('D').mean()  # Resample to daily mean
    .reset_index()
)

#%% Load and process observed data
# Reload the data with the correct delimiter
observed_data = pd.read_csv(observed_file, sep=';', names=['Date', 'Temperature_C'], header=0)

# Convert the datetime column to a proper datetime object
observed_data['Date'] = pd.to_datetime(observed_data['Date'], format='%d.%m.%Y %H:%M', errors='coerce')

# Ensure the temperature is numeric
observed_data['Temperature_C'] = pd.to_numeric(observed_data['Temperature_C'], errors='coerce')

# Drop rows with invalid data
observed_data = observed_data.dropna(subset=['Date', 'Temperature_C'])

# Set datetime as the index for resampling
observed_data.set_index('Date', inplace=True)

# Resample to daily mean
observed_data = observed_data.resample('D').mean()

# Plot the daily mean time series of observed data
plt.figure(figsize=(12, 6))
plt.plot(observed_data.index, observed_data['Temperature_C'], label='Daily Mean Temperature')
plt.title('Daily Mean Temperature Time Series')
plt.xlabel('Date')
plt.ylabel('Temperature (°C)')
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend()
plt.tight_layout()
plt.show()

#%% Merge the datasets on the 'Date' column, keeping only overlapping dates
merged_data = pd.merge(era5_data, observed_data, on='Date', suffixes=('_ERA5', '_Obs'))

#%% Correction du biais sur la moyenne
# Compute mean bias and standard deviation ratio for correction
mean_bias = merged_data['Temperature_C_ERA5'].mean() - merged_data['Temperature_C_Obs'].mean()
std_ratio = merged_data['Temperature_C_Obs'].std() / merged_data['Temperature_C_ERA5'].std()

# Apply mean and standard deviation correction to overlapping data
merged_data['Temperature_C_ERA5_Corrected'] = (
    (merged_data['Temperature_C_ERA5'] - mean_bias) * std_ratio
)

# Apply the same corrections to the entire ERA5 dataset
era5_data['Temperature_C_Corrected'] = (
    (era5_data['Temperature_C'] - mean_bias) * std_ratio
)

# Recompute uncertainties with new corrections
residuals = merged_data['Temperature_C_ERA5_Corrected'] - merged_data['Temperature_C_Obs']
uncertainty_std = residuals.std()

merged_data['Uncertainty_Lower'] = merged_data['Temperature_C_ERA5_Corrected'] - 1.92 * uncertainty_std
merged_data['Uncertainty_Upper'] = merged_data['Temperature_C_ERA5_Corrected'] + 1.92 * uncertainty_std

# Visualization: Corrected vs Observed
plt.figure(figsize=(12, 6))
plt.plot(merged_data['Date'], merged_data['Temperature_C_Obs'], label='Observed Temperature', color='blue')
plt.plot(merged_data['Date'], merged_data['Temperature_C_ERA5'], label='ERA5 Temperature (Original)', color='red')
plt.plot(merged_data['Date'], merged_data['Temperature_C_ERA5_Corrected'], label='ERA5 Temperature (Corrected)', color='green')
plt.fill_between(
    merged_data['Date'],
    merged_data['Uncertainty_Lower'],
    merged_data['Uncertainty_Upper'],
    color='green',
    alpha=0.2,
    label='Uncertainty Bounds (95%)'
)
plt.legend()
plt.title('Temperature Comparison with Bias and Variability Correction')
plt.xlabel('Date')
plt.ylabel('Temperature (°C)')
plt.grid()
plt.tight_layout()
plt.show()

# Scatter plot: Observed vs ERA5 (Original and Corrected)
plt.figure(figsize=(10, 6))
plt.scatter(merged_data['Temperature_C_ERA5'], merged_data['Temperature_C_Obs'], color='blue', alpha=0.6, label='Original ERA5')
plt.scatter(merged_data['Temperature_C_ERA5_Corrected'], merged_data['Temperature_C_Obs'], color='green', alpha=0.6, label='Corrected ERA5')
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

#%% Residuals before and after correction
residuals_before = merged_data['Temperature_C_ERA5'] - merged_data['Temperature_C_Obs']
residuals_after = merged_data['Temperature_C_ERA5_Corrected'] - merged_data['Temperature_C_Obs']

# Plot histograms of residuals before and after correction
plt.figure(figsize=(12, 6))
plt.hist(residuals_before, bins=30, alpha=0.6, color='red', label='Residuals Before Correction', edgecolor='black')
plt.hist(residuals_after, bins=30, alpha=0.6, color='green', label='Residuals After Correction', edgecolor='black')
plt.axvline(x=0, color='black', linestyle='--', label='Zero Residual')
plt.title('Residual Histograms Before and After Correction')
plt.xlabel('Residual (ERA5 - Observed)')
plt.ylabel('Frequency')
plt.legend()
plt.grid(alpha=0.7, linestyle='--')
plt.tight_layout()
plt.show()