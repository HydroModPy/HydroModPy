# -*- coding: utf-8 -*-
"""
Created on Sat Jan 25 10:27:09 2025

@author: roquesc
"""

import os
import geopandas as gpd
import xarray as xr
import rioxarray
import pandas as pd
import matplotlib.pyplot as plt

# Define paths
era5_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
sites_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_database\_spatial\_testing_sites'
output_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_waterwise_process\_climate\_era5'
sites = ["_cont", "_jamt", "_gdsa", "_rech", "_sado", "_zugs", "_peca"]

# Process each site
for site in sites:
    print(f"Processing site: {site}")
    site_folder = os.path.join(sites_folder, site)
    polygon_path = os.path.join(site_folder, "_catchment_bnd", "watershed.shp")
    site_output_folder = os.path.join(output_folder, f"extract_{site}")
    os.makedirs(site_output_folder, exist_ok=True)

    if not os.path.exists(polygon_path):
        print(f"Catchment file not found for site: {site}")
        continue

    variables = ['2m_temperature', 'snow_depth', 'total_precipitation', 'forecast_albedo', 'surface_net_solar_radiation']

    # Load the polygon
    polygon = gpd.read_file(polygon_path)
    polygon = polygon.set_crs('epsg:3035').to_crs(epsg=4326)
    polygon = polygon.buffer(0.01)

    # Visualize the first NetCDF file with the polygon overlay
    first_visualized = False

    # Process each variable
    for variable in variables:
        variable_path = os.path.join(era5_folder, variable)
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

                    # Identify the time dimension dynamically
                    time_dim = None
                    for dim in dataset.dims:
                        if 'time' in dim.lower():
                            time_dim = dim
                            break

                    if not time_dim:
                        raise ValueError("Time dimension not found in the dataset.")

                    # Visualize the first NetCDF file with the polygon overlay
                    if not first_visualized:
                        first_timestep = dataset[list(dataset.data_vars.keys())[0]].isel({time_dim: 0})

                        plt.figure(figsize=(12, 8))
                        first_timestep.plot(cmap="viridis", alpha=0.7)
                        polygon.boundary.plot(ax=plt.gca(), color="red", linewidth=2, label="Polygon Boundary")
                        plt.title(f"NetCDF Data ({variable}) with Polygon Overlay", fontsize=14)
                        plt.legend()
                        plt.xlabel("Longitude")
                        plt.ylabel("Latitude")
                        plt.tight_layout()
                        plt.savefig(os.path.join(site_output_folder, f"polygon_overlay.png"))
                        plt.show()
                        first_visualized = True

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

        # SAVE


        output_file = os.path.join(site_output_folder, f"{variable}.csv")

        combined_df.to_csv(output_file, index=True)

        print(f"Saved data for {site}, {variable} to {output_file}")

    print('###########################################')
    print("Extraction completed for all testing sites!")
    print('###########################################')
