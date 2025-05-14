# -*- coding: utf-8 -*-
"""
Created on Wed Apr 23 15:21:15 2025

@author: delarueo

Extract from cerra alps data local cerra data
Debiased ?
Generate Help input files
statistic timeserie for each catchement
"""

import toolbox_newFuns_ as tb
import os

#%% 
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
deployment_sites = ['asdg','luit','mart','pass','sais','scha','vill','dose']

buffer = 0.2

# Information output
output_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/_waterwise_local_cerra/'
mask_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/_local_cerra_mask/'
tb.create_folder(output_path)
tb.create_folder(mask_path)


#%% Extract local cerra over testing sites + provided weather station
# For new Weather station = location where an air temperature observation data is provided

if 0:
    type_site = 'testing'
    print('>< START >< testing sites')
    
    for site_id in testing_sites:
        # Generate site mask
        # WARNING database structure sensibility
        print(f'> {site_id}')
        print('>> Generate site mask - ' , end = '')
        next_step = True
        try:
            site_shape_path = f'Z:/HDPY_models/CR/20250410/_{site_id}/results_stable/geographic/watershed.shp'
            obs_path = f'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_{type_site}_sites/_{site_id}/_climate/_air_temperature/_observation/'
            obs_paths = [f'{obs_path}{path}/' for path in  os.listdir(obs_path)]
            grid = tb.CERRA(grid_path)
            mask = grid.generate_site_mask(site_id, site_shape_path, obs_paths, output_path,
                                           buffer, catch_crs = 3035, save = mask_path,
                                           checkplot = checkplot, verbose = False)
            grid.__close__()
            print('OKAY')
        except:
            print('FAIL')
            next_step = False
        
        if next_step:
            print('>> Extract local data')
            try:
                local_cerra_file = tb.CERRA.extract_site_data(mask, site_id, 
                                            database_path, variables, years,
                                            output_path, verbose = verbose)
                print(f'{local_cerra_file}')
            except:
                print('FAIL')
        
    print('>< END ><')

## Testing sites - 2
if 0:
    testing_sites_ = ['cont','gdsa','peca','urse']
    type_site = 'testing'
    print('>< START >< testing sites')
    
    for site_id in testing_sites_:
        # Generate site mask
        # WARNING database structure sensibility
        print(f'> {site_id}')
        print('>> Generate site mask - ' , end = '')
        next_step = True
        try:
            site_shape_path = f'Z:/HDPY_models/CR/20250410/_{site_id}/results_stable/geographic/watershed.shp'
            obs_path = f'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_{type_site}_sites/_{site_id}/_climate/_air_temperature/_observation/'
            obs_paths = [f'{obs_path}{path}/' for path in  os.listdir(obs_path)]
            grid = tb.CERRA(grid_path)
            mask = grid.generate_site_mask(site_id, site_shape_path, obs_paths, output_path,
                                           buffer, catch_crs = 3035, save = mask_path,
                                           checkplot = checkplot, verbose = False)
            grid.__close__()
            print('OKAY')
        except:
            print('FAIL')
            next_step = False
            
        if next_step:
            print('>> Extract local data')
            try:
                local_cerra_file = tb.CERRA.extract_site_data(mask, site_id, 
                                            database_path, variables, years,
                                            output_path, verbose = verbose)
                print(f'{local_cerra_file}')
            except:
                print('FAIL')
        
    print('>< END ><')

# TODO: still missing gdsa - peca

#%% From Local cerra to Time serie statistics for variables_ and all available sites (for now testing sites)

# TODO extract catchement statistics
# TODO help grid input

if 0:
    type_site = 'testing'
    print('>< START >< timeserie statistics - testing sites')
    variables_ = ['snow_depth', 'snow_depth_water_equivalent', 'surface_net_solar_radiation']
    
    for var in variables_:
        var_path = f'{database_path}{var}/'
        print(f'> {var} ')
        for site_id in testing_sites:
            data_path = f'{var_path}{var}_{site_id}.nc'
            site_path = f'Z:/HDPY_models/CR/20250410/_{site_id}/results_stable/geographic/watershed.shp'
            output_path_ = f'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_{type_site}_sites/_{site_id}/'
            database_var = database_vars[var]
            output_path_ = f'{output_path_}_climate/_{database_var}/_reanalysis/_cerra_forecast/'
            output_path = f'{output_path_}{var}_timeserie_statistics.csv'
            tb.create_folder(output_path_)
            print(f'>> {site_id}', end = '')
            try: 
                data = tb.CERRA(data_path)
                data.compute_timeserie_statistics(site_path, var, save = output_path)
                print(' OKAY ')
            except:
                print(' FAIL ')
    
    print('>< END ><')


#%% Generate PyHelp Grid input for poschiavo site.

# Step 1 : generate local cerra for poschiavo catchement
if 0:
    print('>> Generate output folder')
    site_id = 'posch'
    output_path = f'./help_input/_{site_id}/'
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
        
    if next_step:
        print('>> Extract local data')
        try:
            local_cerra_file = tb.CERRA.extract_site_data(mask, site_id, 
                                        database_path, variables, years,
                                        output_path, verbose = verbose)
            print(f'{local_cerra_file}')
        except:
            print('FAIL')
        
    print('>< END ><')

# Step 2: Generate pyhelp grid input from local cerra
if 1:
    print('>> Generate output folder')
    site_id = 'posch'
    output_path = f'./help_input/_{site_id}/_from_cerra_forescast/'
    tb.create_folder(output_path)

    
    local_cerra_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'
    
    print('>> Read pyHelp from Base Help File')
    file_path = 'M:/GitHub/HydroModPy-dev-waterwise/users/delarue/pyhelp-copy/poschiavo/input_grid_base1.csv'
    gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(file_path, verbose = True)
    
    for var in variables:
        var_cerra_file = F'{local_cerra_path}/{var}/{var}_{site_id}.nc'    
        print('>> Open variable local cerra')
        data = tb.CERRA(var_cerra_file)
    
        print('>> Generate py help input file')
        timestep = '3H'
        result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var, 
                                        rule = 'linear', timestep = timestep, verbose = True,
                                        save = f'{output_path}{var}_input_data.csv')    
        
    print('>< END ><')    
    
    # print(' >> Open alps cerra')
    # cerra_file = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/2m_temperature/1984/1984_alps.nc'
    # data = tb.CERRA(cerra_file)
    
    # print('>> generate py help input file')
    # timestep = 'D'
    # var = '2m_temperature'
    # result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var, 
    #                                     rule = 'linear', timestep = timestep, verbose = True,
    #                                     save = f'{output_path}test_help_grid_{var}.csv')




# if 0:  
    
    
#     type_site = 'deployment'
#     site_id = 'posch'
#     print('>< START >< generate pyHelp input Poschiavo')
    
#     for var in variables:
#         var_path = f'{database_path}{var}/'
#         print(f'> {var} ')





#             data_path = f'{var_path}{var}_{site_id}.nc'
#             site_path = f'Z:/HDPY_models/CR/20250410/_{site_id}/results_stable/geographic/watershed.shp'
#             output_path_ = f'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_{type_site}_sites/_{site_id}/'
#             database_var = database_vars[var]
#             output_path_ = f'{output_path_}_climate/_{database_var}/_reanalysis/_cerra_forecast/'
#             output_path = f'{output_path_}{var}_timeserie_statistics.csv'
#             tb.create_folder(output_path_)
#             print(f'>> {site_id}', end = '')
#             try: 
#                 data = tb.CERRA(data_path)
#                 data.compute_timeserie_statistics(site_path, var, save = output_path)
#                 print(' OKAY ')
#             except:
#                 print(' FAIL ')
    
#     print('>< END ><')




























#%% Experiemental area
if 0:
    output_path = './test_cerra2helpInput/'
    tb.create_folder(output_path)
    
    file_path = 'M:/GitHub/HydroModPy-dev-waterwise/users/delarue/pyhelp-copy/poschiavo/input_grid_base1.csv'
    gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(file_path, verbose = True)
    
    print(' >> Open alps cerra')
    cerra_file = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/2m_temperature/1984/1984_alps.nc'
    data = tb.CERRA(cerra_file)
    
    print('>> generate py help input file')
    timestep = 'D'
    var = '2m_temperature'
    result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var, 
                                        rule = 'linear', timestep = timestep, verbose = True,
                                        save = f'{output_path}test_help_grid_{var}.csv')

    

#%%




