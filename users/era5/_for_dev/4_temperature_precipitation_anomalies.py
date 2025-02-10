import os
import pandas as pd
import matplotlib.pyplot as plt

#%% Load your hourly temperature data 
# Define paths
base_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'
catch_name = '_urse'

output_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_process\_climate\_era5'
output_folder = os.path.join(output_folder,catch_name)

fig_folder = os.path.join(output_folder, 'fig')

variables = ['2m_temperature', 'snow_depth', 'total_precipitation', 'forecast_albedo']

t2m = variables[0]
tp = variables[2]


#%% Load temperature data
name_t2m = t2m + '.csv'
file_t2m = os.path.join(output_folder, name_t2m)

hourly_df_t2sm = pd.read_csv(file_t2m, index_col=0)
hourly_df_t2sm.index = pd.to_datetime(hourly_df_t2sm.index)

# yearly_t2sm = hourly_df_t2sm['mean'].resample('Y').mean() - 273.15

# # Plot the dataframe
# yearly_t2sm.plot(figsize=(10, 6))
# plt.ylabel('temperature [oC]')
# plt.grid(True)
# plt.tight_layout()

#%% Load precipitation data
name_tp = tp + '.csv'
file_tp = os.path.join(output_folder, name_tp)

hourly_df_tp = pd.read_csv(file_tp, index_col=0)
hourly_df_tp.index = pd.to_datetime(hourly_df_tp.index)

# yearly_tp = hourly_df_tp['mean'].resample('Y').mean()


# # Plot the dataframe
# yearly_tp.plot(figsize=(10, 6))
# plt.ylabel('Total precipitation [mm/y]')
# plt.grid(True)
# plt.tight_layout()

#%% Drop years outside desired range (1990-2023) for temperature data
# years_start = 1980
# years_end = 2023
years_start, years_end = hourly_df_t2sm.index.year.min(), hourly_df_t2sm.index.year.max()
hourly_df_t2sm = hourly_df_t2sm.loc[(hourly_df_t2sm.index.year >= years_start) & (hourly_df_t2sm.index.year <= years_end)]
hourly_df_tp = hourly_df_tp.loc[(hourly_df_tp.index.year >= years_start) & (hourly_df_tp.index.year <= years_end)]

#%% Calculate temperature anomalies relative to a reference period
start_ref = '1980-01-01'
end_ref = '2000-01-01'

# Define the months to include
months_to_include_t2sm = range(6, 9)  # June to October
months_to_include_tp = range(1, 5)
#months_to_include_tp = list(range(10, 13)) + list(range(1, 4))
hourly_df_t2sm = hourly_df_t2sm[hourly_df_t2sm.index.month.isin(months_to_include_t2sm)]
hourly_df_tp = hourly_df_tp[hourly_df_tp.index.month.isin(months_to_include_tp)]

mean_ref_t2sm = hourly_df_t2sm.loc[(hourly_df_t2sm.index >= start_ref) & (hourly_df_t2sm.index <= end_ref), 'mean'].mean()
hourly_df_t2sm['anomaly'] = hourly_df_t2sm['mean'] - mean_ref_t2sm

# Group the temperature data by year to create yearly anomalies
yearly_anomalies_t2sm = hourly_df_t2sm.resample('Y').mean()

# Calculate precipitation anomalies relative to a reference period
mean_ref_tp = hourly_df_tp.loc[(hourly_df_tp.index >= start_ref) & (hourly_df_tp.index <= end_ref), 'mean'].mean()
hourly_df_tp['anomaly'] = (hourly_df_tp['mean'] - mean_ref_tp)/mean_ref_tp*100

# Group the precipitation data by year to create yearly anomalies
yearly_anomalies_tp = hourly_df_tp.resample('Y').mean()

#%% Create the scatter plot
plt.figure(figsize=(8, 6))
sc = plt.scatter(yearly_anomalies_tp['anomaly'], yearly_anomalies_t2sm['anomaly'], c=yearly_anomalies_t2sm.index.year, cmap='jet', marker="o", s=400, zorder=1, lw=1, alpha=1)

# Add labels and title
plt.xlabel('Precipitation Anomaly Jan-May [%]', fontsize=14)
plt.ylabel('Temperature Anomaly Jun-Sept [°C]', fontsize=14)

# Add colorbar
cbar = plt.colorbar(sc)
cbar.ax.tick_params(labelsize=14)  # Increase font size of colorbar ticks

# Add horizontal and vertical lines at x=0 and y=0 with lower zorder
plt.axhline(0, color='black', linewidth=1, zorder=0)
plt.axvline(0, color='black', linewidth=1, zorder=0)

# Add black circles around the scatter plot points
for i, txt in enumerate(yearly_anomalies_t2sm.index.year):
    plt.annotate(txt, (yearly_anomalies_tp['anomaly'][i], yearly_anomalies_t2sm['anomaly'][i]), color='black', fontsize=10, ha='right')

# Set x and y limits to the nearest tick
# plt.xlim([-30,50])
# plt.ylim([-1.5,3])

# Increase font size of tick labels
plt.xticks(fontsize=12)
plt.yticks(fontsize=12)

name_fig = 'precipitation_temperature.png'
fig_name = os.path.join(fig_folder,name_fig)
plt.savefig(fig_name)
