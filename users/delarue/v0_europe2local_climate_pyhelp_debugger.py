"""
@date: 2025-10-20
@lastMod: 2025-11-26
@author: delarueo
@description: Test hypothese explication bug pyhelp
@littleMemo: ...
"""
# %% 
# Import libraries
import toolbox_newFuns_cerra_dev as tb
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
doLocal = 0
doDebiasing = 0
doPyHelpInput = 1
doTimeserie = 1
doFigures = 0

# Processsin parameters
## doLocal
reset = False # overwrite existing site mask if True
localBuffer = 0.1 # buffer around catchment for local cerra extraction (in % of catchment size)
## doPyHelpInput
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
cerraAlps_data_folder = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/' #_{variable}/{year}/{year}_alps.nc
# cerraAlps_data_folder = 'Z:/_waterwise_data_process/_climate/_cerra_land/' #_{variable}/{year}/{year}_alps.nc
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

database_vars = {'2m_temperature': 'air_temperature',
                 'total_precipitation': 'total_precipitation',
                 'snow_depth': 'snow_depth', 
                 'snow_depth_water_equivalent': 'snow_depth_water_equivalent',
                 'surface_net_solar_radiation': 'surface_net_solar_radiation'}

# Define site to process
variables = ['total_precipitation']
years = range(1984, 2022)
sites = ['urse']

extra = '20251126'
#%% 
# For one site only - do Local cerra file
site_id = sites[0]

# okay - 20251020 16:30
if doLocal:
    print('>< START local cerra file ><')
    print(f'> {site_id}')
    print('>> Site mask management - ' , end = '')
    next_step = True
    try:
        site_box_path = f'{catchement_box_folder}_{site_id}/results_stable/geographic/box_buff.shp'
        site_mask_path = f'{cerraLocal_data_folder}_{site_id}/{site_id}_mask.npy'
        grid = tb.CERRA(cerraAlps_grid_file)

        mask = grid.do_site_mask(site_id,
                    site_box_path, 
                    site_mask_path, 
                    catch_crs = 3035,
                    verbose = True, 
                    checkplot = True,  
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
            local_cerra_file = tb.CERRA.extract_site_data(mask, 
                                          site_id, 
                                          cerraAlps_data_folder, 
                                          variables, years,
                                          local_file_struc, 
                                          verbose = verbose)
            print(f'Local CERRA file created at {local_cerra_file}')
        except:
            print('FAIL')
    print('>< END local cerra file ><\n')

#%% 
# For one site only - do Local cerra debiasing
if doDebiasing:
    # TODO implement debiasing function based on waterwise database structure
    print('>< START local cerra debiasing ><')
    print('> todo')
    print('>< END local cerra debiasing ><\n')
    pass

#%% 
# For one site only - do pyHelp inputs
if doPyHelpInput:
    print('>< START pyHelp input generation ><')
    print(f'> {site_id} - pyHelp input generation')
    # pyHelp input grid - 2 options:
        # 1 - create new pyHelp Grid for the area.
        # 2 - load a existing pyHelp grid for the area.

    # Try option 2 if doesn't work fall back to option 1
    try: 
        print('>> Load existing pyHelp grid')
        pyHelp_grid_file = f'{pyHelpInput_data_folder}_{site_id}/{site_id}_grid_pyhelp.csv'
        gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(pyHelp_grid_file, verbose = verbose)

        # Define & create output folder
        output_path = f'{pyHelpInput_data_folder}_{site_id}/'
        tb.create_folder(output_path)
        for variable in variables:
            print(f'>> {variable}')
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                print('>>> Open variable local cerra')
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'>><warning> Local CERRA file not found at {local_cerra_file}, skipping variable')
                continue

            print('>>> Generate pyHelp input file')        
            result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, variable, 
                                            rule = 'linear', timestep = timestep, verbose = True,
                                            save = f'{output_path}{site_id}_{variable}_pyhelp{extra}.csv')
        newGrid = False
        
    except:
            print('FAIL')
            newGrid = True

    # If necessary create a new pyHelp grid
    if newGrid:
        # Define & create output folder
        output_path = f'{pyHelpInput_data_folder}_{site_id}/'
        tb.create_folder(output_path)
        for variable in variables:
            print(f'>> {variable}')
            local_cerra_file = f'{cerraLocal_data_folder}_{site_id}/{site_id}_{variable}.nc'
            if os.path.exists(local_cerra_file):
                print('>>> Open variable local cerra')
                data = tb.CERRA(local_cerra_file)
            else:
                print(f'>><warning> Local CERRA file not found at {local_cerra_file}, skipping variable')
                continue
            
            if newGrid:
                print('>>> Generate new pyHelp grid')
                # open cerra grid as a GeoDataFrame and find internal bounds
                gdf_cerraGrid, yx_cerraGrid, df_yx_cerraGrid = data._extract_gdfGrid()
                bounds = tb.Geo.calculate_internal_bounds(gdf_cerraGrid, shrink_distance = 0.1)  
                # Generate the grid from local cerra grid and processing parameters
                gdf_helpGrid, df_helpGrid = data.create_pyHelpGrid(bounds, spacestep_meters)
                newGrid = False
                if checkplot:
                    print('>>>> display both grids')
                    gdf_cerraGrid = gdf_cerraGrid.set_crs('EPSG:4326', allow_override=True)
                    gdf_helpGrid = gdf_helpGrid.set_crs('EPSG:4326', allow_override=True)
                    tb.Geo.plot_multiple_gdfs([gdf_cerraGrid, gdf_helpGrid], title ='Pixel centers of the grids', labels = ['cerra','pyhelp'], markersize = [100,10])

            print('>>> Generate pyHelp input file')      
            result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, variable, 
                                            rule = 'linear', timestep = timestep, verbose = verbose,
                                            save = f'{output_path}{site_id}_{variable}_pyhelp{extra}.csv')
    
        
    print('>< END pyHelp input generation ><\n')        

#%% 
# For one site only - do local timeserie
if doTimeserie:
    print('>< START local cerra timeserie ><')

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
        
        timeserie_file = f'{output_path}{site_id}_{variable}_timeserie{extra}.csv' 
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
# For one site only - do figures
if doFigures:
    print('>< START climatic figures ><')

    print(f'> {site_id}')
    # paths to needed timeserie files
    t2m_timeserie_file = f'{timeserieLocal_data_folder}_{site_id}/{site_id}_2m_temperature_timeserie{extra}.csv'
    tp_timeserie_file = f'{timeserieLocal_data_folder}_{site_id}/{site_id}_total_precipitation_timeserie{extra}.csv'

    # load temperature timeserie
    if os.path.exists(t2m_timeserie_file):
            print('>>> Open 2m temperature local timeserie')
            t2m = tb.ClimateStats(t2m_timeserie_file, '2m_temperature', site_id)
    else:
        print(f'>><warning> 2m temperature local timeserie file not found at {t2m_timeserie_file}')
    # load temperature timeserie
    if os.path.exists(tp_timeserie_file):
            print('>>> Open total precipitation local timeserie')
            tp = tb.ClimateStats(tp_timeserie_file, 'total_precipitation', site_id)
    else:
        print(f'>><warning> total precipitation local timeserie file not found at {tp_timeserie_file}')


    # Define figure output folder
    output_path = f'{output_figure_folder}_{site_id}/'
    tb.create_folder(output_path)
    

    # Climate strips plots   
    t2m.plot_climate_stripes(output_path, 
                             time_bounds = time_bounds_figures,
                             display = True, verbose = True)
    t2m.reset_data()
    
    # Temperature anomaly
    t2m.plot_monthly_anomaly(output_path, 
                             display = True, verbose = True)
    t2m.reset_data()

    # # XY anomaly    
    df = tb.ClimateStats.plot_XY_anomaly(tp, t2m, output_path)
    print('>< END climate figures ><\n')
# %%
