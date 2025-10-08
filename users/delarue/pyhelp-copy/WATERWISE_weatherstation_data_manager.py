# -*- coding: utf-8 -*-
"""
Creation: 2025-05-19
Modification: 2025-05-19
@author: delarueo

WATERWISE
Extract info about weather station - input from WaterWise database
for now just testing site
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

for site_id in testing_sites:
    # Generate site mask
    # WARNING database structure sensibility
    print(f'> {site_id}')
    
    obs_path = f'M:/crash_zone/_testing_sites/_testing_sites/_{site_id}/_climate/_air_temperature/_observation/'
    list_dir = [path for path in os.listdir(obs_path) if os.path.isdir(f'{obs_path}{path}')]
    list_dir = [path for path in list_dir if path != '_id_station']
    obs_paths = [f'{obs_path}{path}/' for path in list_dir]    

    name_ws = list_dir
    for i in range(len(name_ws)):
        print(f">> {site_id}/{name_ws[i]} \t - \t", end = '')
        try:
            ws = tb.WeatherStation(name_ws[i], obs_paths[i])
            df = ws.info2pdf(site_id)            
            data = pd.concat([data,df])    
            
            print(' Okay')

        except:
            df = pd.DataFrame(columns = ['site', 'id', 'X', 'Y', 'crs', 
                                           'variables', 'comments'], 
                              data = [[site_id, name_ws[i], '', '', '', '', 'info extraction fail']])
            data = pd.concat([data,df]) 
            print('Fail')
            
for site_id in testing_sites:
    # Generate site mask
    # WARNING database structure sensibility
    print(f'> {site_id}')

    obs_path = f'M:/crash_zone/_testing_sites/_testing_sites/_{site_id}/_hydrology/_river_discharge/_observation/'
    list_dir = [path for path in os.listdir(obs_path) if os.path.isdir(f'{obs_path}{path}')]
    list_dir = [path for path in list_dir if path != '_id_station']
    obs_paths = [f'{obs_path}{path}/' for path in list_dir]    

    name_ws = list_dir
    for i in range(len(name_ws)):
        print(f">> {site_id}/{name_ws[i]} \t - \t", end = '')
        try:
            ws = tb.WeatherStation(name_ws[i], obs_paths[i])
            df = ws.info2pdf(site_id)            
            data = pd.concat([data,df])    
            
            print(' Okay')

        except:
            df = pd.DataFrame(columns = ['site', 'id', 'X', 'Y', 'crs', 
                                           'variables', 'comments'], 
                              data = [[site_id, name_ws[i], '', '', '', '', 'info extraction fail']])
            data = pd.concat([data,df]) 
            print('Fail')         
            
data.reset_index(inplace = True)
data.to_csv(f'{output_path}/coordonates_obsersation_{date_label}.csv')
print(f'Informations saved at : {output_path}/coordonates_obsersation_{date_label}.csv')

print('>< END ><')

