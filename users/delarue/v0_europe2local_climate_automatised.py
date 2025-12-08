"""
@date: 2025-10-20
@lastMod: 2025-10-21
@author: delarueo
@description: CERRA example code
@littleMemo: ...
"""
# %% 
# Import libraries
import toolbox_newFuns_cerra as tb
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import os

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from itertools import cycle
import numpy as np

#%%
# Visual settings
plt.style.use('./mypythonstyle_latex.mplstyle')
#%% 
# Display options
checkplot = True
verbose = True
withDate = True

# Processing steps
doLocal = 1
doPyHelpInput = 1
doTimeserie = 1
doFigures = 1

# Processsin parameters
## doLocal
reset = False # overwrite existing site mask if True
localBuffer = 0.1 # buffer around catchment for local cerra extraction (in % of catchment size)

## doPyHelpInput
# pyHelp_vars = ['2m_temperature', 'total_precipitation', 'surface_net_solar_radiation']
pyHelp_vars = ['total_precipitation']
shrink_distance = 0.075  # % to shrink cerra grid bounds for pyHelp grid creation
### Time resolution
timestep = 'D'  # 'D' daily, 'M' monthly
### Step size in meters for pyHelp grid creation
spacestep_meters = 2500
### Extrapolation rule for pyHelp input generation : 'nearest', 'linear'
# extrapolation_rule = 'linear'  

## doFigures
time_bounds_figures = [1985, 2021]

# %%
# Set working directories
# Input data paths
cerraFcAlps_data_folder = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/' #_{variable}/{year}/{year}_alps.nc
cerraLandAlps_data_folder = 'Z:/_waterwise_data_process/_climate/_cerra_land/' #_{variable}/{year}/{year}_alps.nc
cerraAlps_grid_file = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'
catchement_box_folder = 'Z:/HDPY_models/CR/20250410/' #_{siteId}/results_stable/geographic/box_buff.shp

# Output data paths
cerraLocal_data_folder = 'Z:/HDPY_database_forModelling/_climate/_cerra/_local/' #_{siteId}/{siteId}_{variable}.nc
timeserieLocal_data_folder = 'Z:/HDPY_database_forModelling/_climate/_cerra/_timeserie/' #_{siteId}/{siteId}_{variable}_timeserie.csv
pyHelpInput_data_folder = 'Z:/HDPY_database_forModelling/_climate/_cerra/_pyHelpInput/' #_{siteId}/{siteId}_{variable}_pyhelp.csv

# Output visualization path
output_figure_folder = 'Z:/_toolbox_figures/' #_{siteId}/{siteId}_{figId}_{*date}[.png/.jpg/.pdf]

# %%
# Define variables to process
variables = ['2m_temperature', 'total_precipitation',
             'snow_depth', 'snow_depth_water_equivalent',
             'surface_net_solar_radiation',
             '2m_relative_humidity', 
             '10m_wind_speed']
years = range(1984, 2022)
sites = ['pass', 'cont', 'jamt', 'gdsa', 'rech',
         'sado', 'zugs', 'peca', 'urse', 'sais',
         'luit', 'mart', 'scha', 'vill', 'valp', 'asdg']


database_vars = {'2m_temperature': 'air_temperature',
                 'total_precipitation': 'total_precipitation',
                 'snow_depth': 'snow_depth', 
                 'snow_depth_water_equivalent': 'snow_depth_water_equivalent',
                 'surface_net_solar_radiation': 'surface_net_solar_radiation'}

# Define site to process
# cerraFC_variables = ['2m_temperature', 
            #  'snow_depth', 'snow_depth_water_equivalent',
            #  'surface_net_solar_radiation',
            #  '2m_relative_humidity', 
            #  '10m_wind_speed']
cerraFC_variables = []            
cerraLand_variables = ['total_precipitation']
years = range(1984, 2022)
variables = ['2m_temperature', 
             'total_precipitation', 
             'surface_net_solar_radiation']
variables = ['total_precipitation']

#%% 
# From Alps CERRA to local CERRA files

if doLocal:
    print('>< START local cerra file ><')
    for site_id in sites:
        print(f'> {site_id}')
        print('>> Site mask management - ' , end = '')
        next_step = True
        next_step = True
        try:
           
            site_box_path = f'{catchement_box_folder}_{site_id}/results_stable/geographic/box_buff.shp'
            site_mask_path = f'{cerraLocal_data_folder}_{site_id}/{site_id}_mask.npy'
            grid = tb.CERRA(cerraAlps_grid_file)
            
            mask = grid.do_site_mask(site_id,
                        site_box_path, 
                        site_mask_path, 
                        catch_crs = 3035,
                        verbose = verbose, 
                        checkplot = verbose,  
                        save = True,
                        reset = reset,
                        buffer = localBuffer)  
                
            grid.__close__()
            print('OKAY')
        except:
            print('FAIL')
            next_step = False
            
        if next_step:
            print('>> Extract local data')
            try:
                local_file_struc = f'{cerraLocal_data_folder}_{site_id}/{site_id}' 
                # local_cerra_file = tb.CERRA.extract_site_data(mask, 
                #                             site_id, 
                #                             cerraFcAlps_data_folder, 
                #                             cerraFC_variables, years,
                #                             local_file_struc, 
                #                             verbose = verbose)
                local_cerra_file = tb.CERRA.extract_site_data(mask, 
                                            site_id, 
                                            cerraLandAlps_data_folder, 
                                            cerraLand_variables, years,
                                            local_file_struc, 
                                            verbose = verbose)
                print(f'Local CERRA file created at {local_cerra_file}')
            except:
                print('FAIL')
            
        print('>< END local cerra file ><\n')

#%%
# Generate pyHelp input files

if doPyHelpInput:
    print('>< START pyHelp input generation ><')
    for site_id in sites:            
        print(f'> {site_id} - pyHelp input generation')
        # pyHelp input grid - 2 options:
            # 1 - create new pyHelp Grid for the area.
            # 2 - load a existing pyHelp grid for the area.

        # pyHelp grid management
        try: 
            print('>> Load existing pyHelp grid')
            pyHelp_grid_file = f'{pyHelpInput_data_folder}_{site_id}/{site_id}_pyhelp_grid.csv'
            gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(pyHelp_grid_file, verbose = verbose)                      
        except:
                print('FAIL')
                newGrid = True
        # If necessary create a new pyHelp grid
        if newGrid:
            # Define & create output folder
            output_path = f'{pyHelpInput_data_folder}_{site_id}/'
            tb.create_folder(output_path)
            variable = pyHelp_vars[0]
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'Local CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
                continue             
            print('>>> Generate new pyHelp grid')
            # open cerra grid as a GeoDataFrame and find internal bounds
            gdf_cerraGrid, yx_cerraGrid, df_yx_cerraGrid = data._extract_gdfGrid()
            bounds = tb.Geo.calculate_internal_bounds(gdf_cerraGrid, shrink_distance = shrink_distance)  
            # Generate the grid from local cerra grid and processing parameters
            gdf_helpGrid, df_helpGrid = data.create_pyHelpGrid(bounds, spacestep_meters)
            newGrid = False
            if checkplot:
                print('>>>> display both grids')
                gdf_cerraGrid = gdf_cerraGrid.set_crs('EPSG:4326', allow_override=True)
                gdf_helpGrid = gdf_helpGrid.set_crs('EPSG:4326', allow_override=True)
                tb.Geo.plot_multiple_gdfs([gdf_cerraGrid, gdf_helpGrid], title ='Pixel centers of the grids', labels = ['cerra','pyhelp'], markersize = [100,10])

        # Generate pyHelp input file on the defined grid
        print('>>> Generate pyHelp input file')
        # Define & create output folder
        output_path = f'{pyHelpInput_data_folder}_{site_id}/'
        tb.create_folder(output_path)
        for variable in pyHelp_vars:  
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'Local CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
                continue 
            result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, variable, 
                                            rule = 'linear', timestep = timestep, verbose = verbose,
                                            save = f'{output_path}{site_id}_{variable}_pyhelp.csv')
       
    print('>< END pyHelp input generation ><\n')   
#%% Timeserie extraction
if doTimeserie:
    print('>< START local cerra timeserie ><')
    for site_id in sites:
        print(f'> {site_id}')
        for variable in variables:
            print(f'>> {variable}')
            output_path = f'{timeserieLocal_data_folder}_{site_id}/'
            tb.create_folder(output_path)
            # open local cerra
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                print('>>> Open variable local cerra')
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'>><warning> Local CERRA file not found at {local_cerra_file}, skipping variable')
                continue

            # define output location            
            timeserie_file = f'{output_path}{site_id}_{variable}_timeserie.csv' 
            print('>>> Compute timeserie statistics')
            stats = data.compute_timeserie_statistics(variable = variable,
                                                    save = timeserie_file)
            print(f'>>> Timeserie saved at {timeserie_file}')
            
            # plot result
            if checkplot:
                print('>>> Display timeserie statistics')
                fig, ax = plt.subplots(1,1,figsize = [10,5])
                stats.plot(ax = ax)
                ax.yaxis.set_label_text(variable)
                ax.set_title(f'CERRA local timeserie statistics - {site_id} - {variable}')
    print('>< END local cerra timeserie  ><\n')

#%%
if doFigures:
    ANOMALY_SETTINGS_t2m = {'timestep': 'M', 
                        'method': 'mean',
                        'ref_bounds': [pd.Timestamp('1984-01-01'), pd.Timestamp('2000-12-31')]}
    ANOMALY_SETTINGS_tp = {'timestep': 'M', 
                        'method': 'sum',
                        'ref_bounds': [pd.Timestamp('1984-01-01'), pd.Timestamp('2000-12-31')]}
    print('>< START doFigures ><')
    for site_id in sites:
        print(f'SITE: {site_id}')

        # Site plots
        t2m_timeserie_file = f'{timeserieLocal_data_folder}_{site_id}/{site_id}_2m_temperature_timeserie.csv'
        tp_timeserie_file = f'{timeserieLocal_data_folder}_{site_id}/{site_id}_total_precipitation_timeserie.csv'

        # load temperature timeserie
        if os.path.exists(t2m_timeserie_file):
                t2m = tb.ClimateStats(t2m_timeserie_file, '2m_temperature', site_id)
        else:
            print(f'>><warning> 2m temperature local timeserie file not found at {t2m_timeserie_file}')
        # load total precipitation timeserie
        if os.path.exists(tp_timeserie_file):
                tp = tb.ClimateStats(tp_timeserie_file, 'total_precipitation', site_id)
        else:
            print(f'>><warning> total precipitation local timeserie file not found at {tp_timeserie_file}')
       
        output_path = f'{output_figure_folder}_{site_id}/'
        # # Climate strips plot
        # print(f'> Climate strips -', end= ' ')   
        # t2m.plot_climate_stripes(output_path, 
        #                         time_bounds = time_bounds_figures,
        #                         display = True, verbose = True)
        # t2m.reset_data()

        # Anomaly plots
        print(f'> Anomaly plot :')   
        t2m.plot_monthly_anomaly(output_path, fig_formats = ['png','pdf'], 
                             time_bounds = [], plot_settings = {}, 
                             anomaly_settings = ANOMALY_SETTINGS_t2m,
                             display = False, verbose = True)
        t2m.reset_data()

        tp.plot_monthly_anomaly(output_path, fig_formats = ['png','pdf'], 
                             time_bounds = [], plot_settings = {}, 
                             anomaly_settings = ANOMALY_SETTINGS_tp,
                             display = False, verbose = True)
        tp.reset_data()


        # XY anomaly plot
        print(f'> XY anomaly plot -', end= ' ')  
        df, fileFig = tb.ClimateStats.plot_XY_anomaly(tp, t2m, output_path)
        print(f'Figure saved at {fileFig}')
        t2m.reset_data()
        tp.reset_data()

        # # Negative days plot
        # print(f'> Negative plot -', end= ' ')  
        # fileFig = t2m.plot_negDays(output_path, time_bounds= time_bounds_figures)
        # print(f'Figure saved at {fileFig}')

    print('>< END doFigures ><\n')

#%%

# timeserie_file = f'{output_path}cont_total_precipitation_timeserie.csv' 
# stats = tb.ClimateStats(timeserie_file, 'total_precipitation', 'cont')

# fig, ax = plt.subplots(1,1,figsize = [10,5])
# stats.data_origin.plot(ax = ax)
# ax.yaxis.set_label_text(variable)
# ax.set_title(f'CERRA local timeserie statistics - {site_id} - {variable}')
# global_stats = [stats.data_origin.max(),
#                 stats.data_origin.mean(),
#                 stats.data_origin.min()]
                
# print(global_stats)
# # %%
# timeserie_file = f'{cerraLocal_data_folder}/_urse/urse_surface_net_solar_radiation.nc'
# data = tb.CERRA(timeserie_file)
# %%
workshop = False

if workshop:
    print('>< START workshop ><')
    for site_id in sites:            
        print(f'> {site_id} - pyHelp input generation')
        # pyHelp input grid - 2 options:
            # 1 - create new pyHelp Grid for the area.
            # 2 - load a existing pyHelp grid for the area.

        # pyHelp grid management
        try: 
            print('>> Load existing pyHelp grid')
            pyHelp_grid_file = f'{pyHelpInput_data_folder}_{site_id}/{site_id}_pyhelp_grid.csv'
            gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(pyHelp_grid_file, verbose = verbose)                      
        except:
                print('FAIL')
                newGrid = True
        # If necessary create a new pyHelp grid
        if newGrid:
            # Define & create output folder
            output_path = f'{pyHelpInput_data_folder}_{site_id}/'
            tb.create_folder(output_path)
            variable = pyHelp_vars[0]
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'Local CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
                continue             
            print('>>> Generate new pyHelp grid')
            # open cerra grid as a GeoDataFrame and find internal bounds
            gdf_cerraGrid, yx_cerraGrid, df_yx_cerraGrid = data._extract_gdfGrid()
            bounds = tb.Geo.calculate_internal_bounds(gdf_cerraGrid, shrink_distance = shrink_distance)  
            # Generate the grid from local cerra grid and processing parameters
            gdf_helpGrid, df_helpGrid = data.create_pyHelpGrid(bounds, spacestep_meters)
            newGrid = False
            if checkplot:
                print('>>>> display both grids')
                gdf_cerraGrid = gdf_cerraGrid.set_crs('EPSG:4326', allow_override=True)
                gdf_helpGrid = gdf_helpGrid.set_crs('EPSG:4326', allow_override=True)
                tb.Geo.plot_multiple_gdfs([gdf_cerraGrid, gdf_helpGrid], title ='Pixel centers of the grids', labels = ['cerra','pyhelp'], markersize = [100,10])

        # Generate pyHelp input file on the defined grid
        print('>>> Generate pyHelp input file')
        # Define & create output folder
        output_path = f'{pyHelpInput_data_folder}_{site_id}/'
        tb.create_folder(output_path)
        for variable in pyHelp_vars:  
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                data = tb.CERRA(local_cerra_file)
                data.dataset[variable] = data.dataset[variable]*6*60*60 # correction previous wrong conversion J to W
                data.__save__(f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}_corr.nc')
            else:
                print(f'Local CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
                continue 
            result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, variable, 
                                            rule = 'linear', timestep = timestep, verbose = verbose,
                                            save = f'{output_path}{site_id}_{variable}_pyhelp_20251110.csv')

#%%