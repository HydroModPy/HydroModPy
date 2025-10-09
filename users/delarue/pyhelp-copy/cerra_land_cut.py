# -*- coding: utf-8 -*-
"""
Created on Wed Jun 25 10:51:10 2025

@author: delarueo






"""
import toolbox_newFuns_ as tb
import os

#%% 
# Display options
checkplot = True
verbose = True

# Information cerra data
database_path = 'D:/_cerra_land_tp/'

years = ['19842000','20012022']
variables = ['total_precipitation']

database_vars = {'2m_temperature': 'air_temperature',
                 'total_precipitation': 'total_precipitation',
                 'snow_depth': 'snow_depth', 
                 'snow_depth_water_equivalent': 'snow_depth_water_equivalent',
                 'surface_net_solar_radiation': 'surface_net_solar_radiation'}

# Information grid catchement 
grid_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'
testing_sites = ['cont','gdsa','jamt','peca','rech','sado','urse','zugs']
deployment_sites = ['asdg','luit','mart','pass','sais','scha','vill','dose']

buffer = 0.2

# Information output
output_path = database_path
mask_path = database_path
tb.create_folder(output_path)
tb.create_folder(mask_path)

#%% generate local cerra poschiavo

print('>> Generate output folder')
site_id = 'posch'
output_path = f'./help_input/_{site_id}/'
combine_file = f'D:/_cerra_land_tp/tp_land_{site_id}.nc'
tb.create_folder(output_path)

print('>> Read pyHelp from Base Help File')
file_path = 'M:/GitHub/HydroModPy-dev-waterwise/users/delarue/pyhelp-copy/poschiavo/input_grid_base1.csv'
gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(file_path, verbose = True)

print('>> Generate local area mask')

next_step = True
try:
    site_shape_path = f'{output_path}/help_grid.shp'
    gdf_helpGrid.to_file(site_shape_path)  

    grid = tb.CERRA(grid_path)
    mask = grid.generate_site_mask(site_id, site_shape_path, [], output_path,
                                   0.2, catch_crs = 4326, save = False,
                                   checkplot = checkplot, verbose = True)
    grid.__close__()
    print(' OKAY')
except:
    print('FAIL to generate mask')
    next_step = False
    
    
list_paths = [f'D:/_cerra_land_tp/{years}_alps.nc' for years in ['19842000','20012022']]
if next_step:
    print('>> Extract local data')
    try:
        local_cerra_file = tb.CERRA.extract_site_data_(mask, site_id,
                                                list_paths, output_path, 
                                                combine_file, verbose = True)
        print(f'{local_cerra_file}')
    except:
        print('FAIL')
    
print('>< END ><')