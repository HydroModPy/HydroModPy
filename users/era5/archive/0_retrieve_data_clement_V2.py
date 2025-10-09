import os
import geopandas as gpd
import xarray as xr
import rioxarray
import pandas as pd
import matplotlib.pyplot as plt

# Define paths
base_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'
catch_name = 'urse'
output_folder = os.path.join(base_path,catch_name)
#r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly\extract'
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
variables = ['2m_temperature', 'snow_depth', 'total_precipitation', 'forecast_albedo']

# Load the polygon
polygon = gpd.read_file(polygon_path)
polygon = polygon.set_crs('epsg:3035').to_crs(epsg=4326)

# Ensure the output folders exist
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
            if month_file.endswith('.nc'):
                file_path = os.path.join(year_path, month_file)

                # Open the NetCDF file
                dataset = xr.open_dataset(file_path, chunks={'time': 0})
                dataset = dataset.assign_coords(longitude=(((dataset.longitude + 180) % 360) - 180)).sortby('longitude')

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
    combined_df = pd.concat(all_data, ignore_index=True)
    output_file = os.path.join(output_folder, f"{variable}_combined.csv")
    combined_df.to_csv(output_file, index=False)
    print(f"Saved combined data for {variable} to {output_file}")

print("Extraction completed.")
