import os
import geopandas as gpd
import xarray as xr
import rioxarray
 
import pandas as pd
import matplotlib.pyplot as plt

# Define paths
base_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'
catch_name = '_urse'
output_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_process\_climate\_era5'
output_folder = os.path.join(output_folder,catch_name)
#r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly\extract'
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
# variables = 
variables = ['total_precipitation']

# Load the polygon
polygon = gpd.read_file(polygon_path)
polygon = polygon.set_crs('epsg:3035').to_crs(epsg=4326) 

#%% Here include the code to check the ncdf and bnd intercept


#%% Ensure the output folders exist
os.makedirs(output_folder, exist_ok=True)
fig_folder = os.path.join(output_folder, 'fig')
os.makedirs(fig_folder, exist_ok=True)

# Process each variable
for variable in variables:
    variable_path = os.path.join(base_path, variable)
    all_data = []

    # Process each year
    for year in sorted(os.listdir(variable_path)):
        year_path = os.path.join(variable_path, year)
        print(f"Processing {variable}, year {year}")

        # Process each month's NetCDF file
        for month_file in sorted(os.listdir(year_path)):
            print(f"{month_file}")
            if month_file.endswith('.nc'):
                file_path = os.path.join(year_path, month_file)

                # Open the NetCDF file
                try:
                    dataset = xr.open_dataset(file_path, chunks={'time': 0})
                    dataset = dataset.assign_coords(longitude=(((dataset.longitude + 180) % 360) - 180)).sortby('longitude')
                except Exception as e:
                    print(f"Failed to open {file_path}: {e}")
                    continue
                # dataset = xr.open_dataset(file_path, chunks={'time': 0})
                # dataset = dataset.assign_coords(longitude=(((dataset.longitude + 180) % 360) - 180)).sortby('longitude')

                # Identify the time dimension dynamically
                time_dim = None
                for dim in dataset.dims:
                    if 'time' in dim.lower():
                        time_dim = dim
                        break

                if not time_dim:
                    raise ValueError("Time dimension not found in the dataset.")

                # Clip the data to the polygon
                dataset = dataset.rio.write_crs("epsg:4326", inplace=True)
                clipped_data = dataset.rio.clip(polygon.geometry, polygon.crs, drop=True)

                # Compute mean, min, max, and standard deviation
                stats = {
                    'mean': clipped_data.mean(dim=['latitude', 'longitude']),
                    'min': clipped_data.min(dim=['latitude', 'longitude']),
                    'max': clipped_data.max(dim=['latitude', 'longitude']),
                    'std': clipped_data.std(dim=['latitude', 'longitude'])
                }

                # Collect data into a unified DataFrame
                df = pd.DataFrame()
                for stat, data_array in stats.items():
                    stat_df = data_array.to_dataframe()
                    stat_df = stat_df.reset_index()
                    df[stat] = stat_df.iloc[:, -1]  # Append the last column containing the stats

                # Add datetime column
                if time_dim in dataset.coords:
                    df['datetime'] = pd.to_datetime(stat_df[time_dim]).dt.strftime('%Y/%m/%d %H:%M')

                df['variable'] = variable
                all_data.append(df)

    # Combine all data for the variable and save as a single CSV
    combined_df = pd.concat(all_data, ignore_index=False)
    combined_df.set_index('datetime', inplace=True)
    combined_df.index = pd.to_datetime(combined_df.index, errors='coerce')
    # Reorder the dataframe chronologically by sorting the index
    combined_df = combined_df.sort_index()
    
    #%% Here add a plot with three subplots showing hourly, daily, monthly and yearly timeseries of hourly_df['mean']
    # Add a plot with three subplots for hourly, daily, monthly, and yearly time series
    fig, axs = plt.subplots(3, 1, figsize=(15, 12), sharex=True)

    # Hourly data
    axs[0].plot(combined_df.index, combined_df['mean'], color='blue', linewidth=0.5, label='Hourly Mean')
    axs[0].set_title('Hourly', fontsize=14)
    axs[0].set_ylabel(f"{variable}", fontsize=12)
    axs[0].legend(loc='upper right', fontsize=10)

    # Daily data
    daily_mean = combined_df['mean'].resample('D').mean()
    axs[1].plot(daily_mean.index, daily_mean, color='orange', linewidth=0.7, label='Daily Mean')
    axs[1].set_title('Daily', fontsize=14)
    axs[1].set_ylabel(f"{variable}", fontsize=12)
    axs[1].legend(loc='upper right', fontsize=10)

    # Monthly and yearly data
    monthly_mean = combined_df['mean'].resample('M').mean()
    yearly_mean = combined_df['mean'].resample('Y').mean()

    axs[2].plot(monthly_mean.index, monthly_mean, color='green', linewidth=1, label='Monthly Mean')
    axs[2].plot(yearly_mean.index, yearly_mean, color='red', linewidth=1.5, label='Yearly Mean')
    axs[2].set_title('Monthly and Yearly', fontsize=14)
    axs[2].set_ylabel(f"{variable}", fontsize=12)
    axs[2].legend(loc='upper right', fontsize=10)

    # Common X-axis label
    axs[2].set_xlabel('Time', fontsize=12)

    # Improve layout and add grid lines
    for ax in axs:
        ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.7)

    plt.tight_layout()
    plt.show()
    plt.close()

    # # Save the figure
    
    # name_fig = f"{variable}.png"
    # timeseries_fig_name = os.path.join(output_folder, name_fig)
    # fig.savefig(timeseries_fig_name)
    
    # # Save the csv file
    # output_file = os.path.join(output_folder, f"{variable}.csv")
    # combined_df.to_csv(output_file, index=True)
    # print(f"Saved combined data for {variable} to {output_file}")

print("Extraction completed.")
