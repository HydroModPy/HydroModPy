# -*- coding: utf-8 -*-
"""
Created on Mon May 26 09:44:02 2025

@author: delarueo
"""

import toolbox_newFuns_ as tb
import os
import pandas as pd

#%%
date_label = '20250523'
# Display options
checkplot = True
verbose = True

# Information cerra data
database_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'

years = range(1984, 2023)
variables = ['2m_temperature', 'total_precipitation',
             'snow_depth', 'snow_depth_water_equivalent',
             'surface_net_solar_radiation']
database_vars = {'2m_temperature': 'air_temperature',
                 'total_precipitation': 'total_precipitation',
                 'snow_depth': 'snow_depth', 
                 'snow_depth_water_equivalent': 'snow_depth_water_equivalent',
                 'surface_net_solar_radiation': 'surface_net_solar_radiation'}

# Information grid catchement 
grid_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'
testing_sites = ['cont','gdsa','jamt','peca','rech','sado','urse','zugs']
deployment_sites = ['alsg','luit','mart','pass','sais','scha','vill','dose']

buffer = 0.2

# Information output
output_path = './waterwise/observation_stations/'
tb.create_folder(output_path)

#%%

type_site = 'testing'
data = pd.DataFrame()

print('>< START >< testing sites')
data = pd.DataFrame(columns = ['site', 'id',
                               'X', 'Y', 'crs', 
                               'variables', 'comments'])
testing_sites = ['sado']
for site_id in testing_sites:
    # Generate site mask
    # WARNING database structure sensibility
    print(f'> {site_id}')
    
obs_path = f'M:/crash_zone/_testing_sites/_testing_sites/_{site_id}/_climate/_air_temperature/_observation/_MALGA SADOlE/'

    
ws_sado = tb.WeatherStation('malga_sadole', obs_path, variables=['2m_temperature'])

df_T = ws_sado._data['2m_temperature']
#%%
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 10))
      
# Plot each GeoDataFrame in the list

df_T.plot(ax = ax, y = '2m_temperature_malga_sadole', ls = ':' , marker = '+', color = 'black')
ax.set_xlim(['2015-01','2015-07'])

#%%
df_t_selec = df_T.loc[(df_T.index >='2015-01-01') & (df_T.index <= '2015-07-01'), :]
fig, ax = plt.subplots(figsize=(10, 10))
      
# Plot each GeoDataFrame in the list

df_t_selec.plot(ax = ax, y = '2m_temperature_malga_sadole', ls = ':' , marker = '+', color = 'black')
# ax.set_xlim(['2016-01','2016-07'])
