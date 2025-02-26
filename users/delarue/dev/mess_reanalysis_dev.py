# -*- coding: utf-8 -*-
"""
Created on Thu Jan 30 14:57:19 2025

@author: delarueo
"""
    # def display_timestep_with_cartopy(self, variable_name, timestep_index=0, colormap='viridis'):
    #     # Extract data as before
    #     variable_data = self.dataset[variable_name]
    #     time_step_data = variable_data.isel(time=timestep_index).fillna(0)
        
    #     # Create a Cartopy map
    #     fig, ax = plt.subplots(1, 1, figsize=(10, 6), subplot_kw={'projection': ccrs.PlateCarree()})
        
    #     # Plot the data on the map using Cartopy
    #     im = ax.imshow(time_step_data, cmap=colormap, origin='lower', transform=ccrs.PlateCarree())
        
    #     # Add coastlines for reference
    #     ax.coastlines()
        
    #     # Add colorbar
    #     fig.colorbar(im, ax=ax, orientation="vertical", label=variable_name)
        
    #     # Formatting time label
    #     time_label = self.dataset['time'].isel(time=timestep_index).values
    #     if isinstance(time_label, np.datetime64):
    #         time_label = pd.to_datetime(time_label).strftime('%Y-%m-%d %H:%M:%S')
        
    #     ax.set_title(f"{variable_name} at Time Step {timestep_index} ({str(time_label)})")
    #     ax.set_xlabel('Longitude')
    #     ax.set_ylabel('Latitude')
        
    #     plt.show()
        
    #     return ax
#%%

t_C = era5_data.dataset.temperature_2m_C.isel(time=0)
# Extract the time for the plot title (assuming time is in the 'time' variable)
time_label = era5_data.dataset['time'].isel(time=0).values
# Convert to a human-readable format (e.g., using pandas if it's a numpy.datetime64 object)
time_str = pd.to_datetime(time_label).strftime('%Y-%m-%d %H:%M:%S')


fig = plt.figure(figsize=(9,6))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.coastlines()
ax.gridlines()
t_C.plot(ax=ax, 
         transform=ccrs.PlateCarree(),         
         cbar_kwargs={'shrink': 0.4,
                      'label' :'Temperature (°C)',
                      'extend':'neither'})

polygon.plot(ax=ax, color='yellow', alpha=0.5, edgecolor='black', linewidth=10)
        
ax.set_title(f"Temperature at 2 m ({time_str})")

#%%
# Extract the temperature data for the first time step
t_C = era5_data.dataset.temperature_2m_C.isel(time=0)

# Extract the time for the plot title (assuming 'time' variable exists in your dataset)
time_label = era5_data.dataset['time'].isel(time=0).values
# Convert to a human-readable format (e.g., using pandas if it's a numpy.datetime64 object)
time_str = pd.to_datetime(time_label).strftime('%Y-%m-%d %H:%M:%S')

# Create the figure and axis with PlateCarree projection (latitude/longitude)
fig = plt.figure(figsize=(10, 15))
ax = plt.axes(projection=ccrs.PlateCarree())

# Add coastlines and gridlines
ax.coastlines()
ax.add_feature(cfeature.BORDERS, linestyle=':')
ax.gridlines(draw_labels=True)  # Adding latitude and longitude labels

# Set custom limits to focus around a catchment (e.g., lat/lon bounding box)
# Example coordinates: [min_lon, max_lon, min_lat, max_lat]
catchment_extent = map_extent(era5_data, buffer = 0)
print(catchment_extent)

ax.set_extent(catchment_extent, crs=ccrs.PlateCarree())

# Plot the temperature data
t_C.plot(ax=ax, 
         transform=ccrs.PlateCarree(),         
         cbar_kwargs={'shrink': 0.3,
                      'label': 'Temperature (°C)',
                      'extend': 'neither'})

# Ensure the polygon is in the correct CRS (WGS84 / EPSG:4326)
polygon = polygon.to_crs(epsg=4326)  # Make sure the CRS matches

# Plot the polygon
polygon.plot(ax=ax, color='yellow', alpha=1, linewidth=2)

# Set the title with the time reference
ax.set_title(f"Temperature at 2 m ({time_str})")


# Show the plot
plt.show()



# def display_timestep_2(self, variable_name, timestep_index=0):
#     """
#     Display a specific time step for a given variable from the NetCDF dataset.
    
#     :param variable_name: Name of the variable to plot (e.g., 'temperature', 'u10', etc.)
#     :param timestep_index: Index of the time step to display (default is 0, i.e., the first time step)
#     """
#     # Extract the variable data from the dataset
#     variable_data = self.dataset[variable_name]

#     # Select the data for the given time step
#     time_step_data = variable_data.isel(time = timestep_index)
#     # Extract the time for the plot title (assuming 'time' variable exists in your dataset)
#     time_label = era5_data.dataset['time'].isel(time=0).values
#     # Convert to a human-readable format (e.g., using pandas if it's a numpy.datetime64 object)
#     time_str = pd.to_datetime(time_label).strftime('%Y-%m-%d %H:%M:%S')
    
#     # Plotting
#     # Create the figure and axis with PlateCarree projection (latitude/longitude)
#     fig = plt.figure(figsize=(10, 15))
#     ax = plt.axes(projection=ccrs.PlateCarree())

#     # Add coastlines and gridlines
#     ax.coastlines()
#     ax.add_feature(cfeature.BORDERS, linestyle=':')
#     ax.gridlines(draw_labels=True)  # Adding latitude and longitude labels

#     # Set custom limits to focus around a catchment (e.g., lat/lon bounding box)
#     # Example coordinates: [min_lon, max_lon, min_lat, max_lat]
#     catchment_extent = map_extent(era5_data)
#     ax.set_extent(catchment_extent, crs=ccrs.PlateCarree())

#     # Plot the temperature data
#     t_C.plot(ax=ax, 
#              transform=ccrs.PlateCarree(),         
#              cbar_kwargs={'shrink': 0.3,
#                           'label': 'Temperature (°C)',
#                           'extend': 'neither'})

#     # # Ensure the polygon is in the correct CRS (WGS84 / EPSG:4326)
#     # polygon = polygon.to_crs(epsg=4326)  # Make sure the CRS matches

#     # # Plot the polygon
#     # polygon.plot(ax=ax, color='yellow', alpha=1, linewidth=2)

#     # Set the title with the time reference
#     ax.set_title(f"Temperature at 2 m ({time_str})")


#     # Show the plot
#     plt.show()
           
    
#     # Plotting
#     # Assuming the data is on a 2D grid with latitude and longitude
#     fig, ax = plt.subplots(1, 1, figsize=(10, 6))
#     time_step_data.plot(cmap='viridis', add_colorbar=True)

#     # Adding a title with the time step information
#     time_label = self.dataset['time'].isel(time=timestep_index).values
    
#     ax.set_title(f"{variable_name} at Time Step {timestep_index} ({str(time_label)})")
#     ax.set_xlabel('Longitude')
#     ax.set_ylabel('Latitude')

#     plt.show()
    
#     return ax

    
    
# def map_extend(region, buffer=0):
    
#     if region == 'europe':
#         extent = [-10, 30, 20, 70]  # Full global view
#     elif region == 'alpes':
#         # Focus on the Alps (approx. region)
#         extent = [4, 17, 43, 49]   
#     elif isinstance(region, gpd.GeoDataFrame):
#         # Focus on a specific catchment area and include buffer space
#         [lon_min,lat_min,lon_max,lat_max] = polygon.total_bounds 
#         lon_extend = lon_max - lon_min
#         lat_extend = lat_max - lat_min

#         extent = [lon_min - buffer*lon_extend,
#                   lon_max + buffer*lon_extend,
#                   lat_min - buffer*lat_extend,
#                   lat_max + buffer*lat_extend]
#     else:
#         raise ValueError("Invalid region.")
#         extent = [-10, 30, 20, 70]
    
#     return extent




