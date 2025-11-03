"""
@date: 2025-04-07
@lastMod: 2025-09-23
@author: delarueo
@description: Toolbox Tester
@littleMemo: ...
"""
#%%
import toolbox_newFuns_cerra as tb
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import os

#%% test selector

geoTest = 0
cerraTest = 0  
wsTest = 0
helpTest = 0
debiasTest = 0
localCerraTest = 0
testDebiasing = 0
testTimeserieStats = 0
testClimateStats = 1

#%%
output = 'M:/crash_zone/'

#%% class Geo test

if geoTest:
    path_catchement = 'M:/crash_zone/catchements/'
    sites = ['cont','urse','peca', 'jamt', 'zugs']
    paths = [f'{path_catchement}watershed_{s}.shp' for s in sites]
    
    
    gdfs = [gpd.read_file(p) for p in paths]
    
    #test plot_multi_gdfs (gdf = geodataframes - geopandas package)
    tb.Geo.plot_multiple_gdfs(gdfs, labels = sites)

#%% class CERRA test

if cerraTest:
    
    cerra_path = './test_data/1984_alps.nc'

    # test __init__
    print('> CERRA init')
    data = tb.CERRA(cerra_path, to_standard = False)    
    print(data.dataset)
    print()
    
    # test to_standard
    print('> CERRA to_standard')
    data.to_standard()    
    print(data.dataset)
    print()
    
    # test generate_gridFile
    print('> CERRA generate_gridFile')
    grid = tb.CERRA.generate_gridFile(cerra_path, f'{output}grid_test.nc')    
    print(grid)
    print()

    # test _extract_gdfGrid
    print('> CERRA _extract_gdfGrid')
    gdf_yx, yx, df_yx = data._extract_gdfGrid()    
    print(f'yx:\n{yx[0:5]}\n')
    print(f'df_yx:\n{df_yx.head(5)}\n')
    print(f'gdf_yx:\n{gdf_yx.head(5)}\n')
    
    print('> CERRA _extract_gdfGrid  - change crs')
    gdf_yx, yx, df_yx = data._extract_gdfGrid(dst_crs = 3035)
    print(f'gdf_yx:\n{gdf_yx.head(5)}\n')

    # test _find_nearest_point
    print('> CERRA _find_nearest_point')
    result = data._find_nearest_point(46.33, 10, direction = 'se', work_crs = 3035, checkplot = True)
    print(result, end = '\n\n')
    
    print('> CERRA _find_nearest_point - *each*')
    result = data._find_nearest_point(46.33, 10, direction = 'each', work_crs = 3035, checkplot = True)
    print(result, end = '\n\n')

    print('> CERRA extract_site_data')
    database_folder = 'Z:/_waterwise_teams_database/_save/_20250319/'
    output_folder = './masks/'
    type_site = 'testing'
    site_id = 'urse'
    buffer = 0.2
    site_shape_path = f'{database_folder}_spatial/_{type_site}_sites/_{site_id}/_catchment_bnd/watershed.shp'
    obs_path = f'{database_folder}_time_series/_{type_site}_sites/_{site_id}/_climate/'  
    
    mask = data.generate_site_mask(site_id, 
                                   site_shape_path, obs_path, output_folder,
                                   buffer, catch_crs = 3035,
                                   checkplot =True)

    print('> CERRA generate_site_data')
    cerra_path= 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'
    output_path = 'C:/Users/delarueo/Desktop/crash_zone/_'
    variables = ['2m_temperature']
    years = range(1984,1990)
    
    tb.CERRA.extract_site_data(mask, site_id, cerra_path, variables, 
                                     years, output_path, verbose = True)

    
#%% Help function test

if helpTest:
    cerra_file = 'C:/Users/delarueo/Desktop/crash_zone/2m_temperature_urse.nc'
    data = tb.CERRA(cerra_file)
    output_path = './test_help_input/'
    tb.create_folder(output_path)
    
    print('> open cerra grid as a GeoDataFrame and find internal bounds')
    gdf_cerraGrid, yx_cerraGrid, df_yx_cerraGrid = data._extract_gdfGrid()

    print('> generate GeoDataFrame of the pixel centers of the new grid')
    step_meters = 2500  # Step size in meters
    bounds = tb.Geo.calculate_internal_bounds(gdf_cerraGrid, shrink_distance = 0.1)    

    print('> Generate the grid')
    gdf_helpGrid, df_helpGrid = data.create_pyHelpGrid(bounds, step_meters)

    print('> display both grids')
    gdf_cerraGrid = gdf_cerraGrid.set_crs('EPSG:4326', allow_override=True)
    gdf_helpGrid = gdf_helpGrid.set_crs('EPSG:4326', allow_override=True)
    tb.Geo.plot_multiple_gdfs([gdf_cerraGrid, gdf_helpGrid], title ='Pixel centers of the grids', labels = ['cerra','pyhelp'], markersize = [100,10])

    timestep = 'M'
    var = '2m_temperature'
    result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var, 
                                        rule = 'linear', timestep = timestep, 
                                        save = f'{output_path}test_help_grid_{var}.csv')

    
    # print('> CERRA test generate_localHelp')
    # grid_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'
    # cerra_path= 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'
    # # output_path = 'C:/Users/delarueo/Desktop/crash_zone/_'
    # variables = ['2m_temperature']
    # years = range(1984,1990)
    
    # database_folder = 'Z:/_waterwise_teams_database/_save/_20250319/'
    # output_path = './generate_localHelp/'
    # type_site = 'testing'
    # site_id = 'urse'
    # buffer = 0.2
        
    # grid = tb.CERRA(grid_path)
    # grid.generate_localHelp(cerra_path, site_shape_path, obs_path, output_path,
    #                         site_id, type_site, variables, years, buffer = 0.2)

#%%   Weather station class

if wsTest: 
    path_ws = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/_sado/_climate/_air_temperature/_observation/_MALGA_SADOLE/'    
    ws = tb.WeatherStation(name = 'malga sadole', path = path_ws, variables = ['2m_temperature'])
    print(ws._infos)
    print(ws._gdf)
    print(ws._data)
    
    
    
#%%   class CERRA - generate Local cerra

if localCerraTest :    
    grid_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc'
    cerra_path= 'Z:/_waterwise_data_process/_climate/_cerra_forecast/'
    output_path = './output_debias_test/'
    tb.create_folder(output_path)
    
    variables = ['2m_temperature']
    years = range(2013,2022)
    verbose = True
    checkplot = True
    
    type_site = 'testing'
    site_id = 'zugs'
    buffer = 0.2
    
    site_shape_path = f'Z:/HDPY_models/CR/20250410/_{site_id}/results_stable/geographic/watershed.shp'
    # manually enter mobilisation path
    obs_path = f'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/_{site_id}/_climate/_air_temperature/_observation/'
    obs_paths = [f'{obs_path}{path}/' for path in  os.listdir(obs_path)]

    print(f'> create local dataset cerra  - {site_id}')   
    grid = tb.CERRA(grid_path)
    mask = grid.generate_site_mask(site_id, site_shape_path, obs_paths, output_path,
                                   buffer, catch_crs = 3035,
                                   checkplot =True, verbose = verbose)
    grid.__close__()
    local_cerra_file = tb.CERRA.extract_site_data(mask, site_id, 
                                   cerra_path, variables, years,
                                   output_path, verbose = True)
    
    print(f'> local cerra file : {local_cerra_file}')
    
    
#%% Debiasing data

if testDebiasing:

    print('> create debiaser')
    checkplot = True
    
    # Info Observation station
    station_path = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/_rech/_climate/_air_temperature/_observation/RO/'
    station_name = 'station'
        
    # Info local site & cerra data
    type_site = 'testing'
    site_id = 'rech'
    var = '2m_temperature'
    local_cerra_file = f'Z:/_waterwise_data_process/_climate/_cerra_forecast/{var}/{var}_{site_id}.nc'  

    # Info Output debiased cerra data
    output_path = './output_debias_test/'
    debiased_cerra_file = f'{output_path}{var}_{site_id}_debias.nc'
    # method = 'LinearScaling'
    method = 'QuantileMappingReplace'
    
    # Open local cerra data
    print('>> open local cerra data')
    local_cerra  = tb.CERRA(local_cerra_file)    
    print('>> open weather station data')
    ws = tb.WeatherStation(station_name, station_path, variables = [var])
    print('>> find nearest cerra pixel to the weather station')
    pixel_ws = local_cerra._find_nearest_point(ws._point.y, ws._point.x, direction = 'all', checkplot = checkplot)
    
    print('>> define DataFrame for debiaser building')
    station_data = ws._data[var]
    pixel_data = pd.DataFrame( {'time': local_cerra.dataset['time'].values,
                                f'{var}_cerra': local_cerra.dataset[var][:,pixel_ws['y']['all'],pixel_ws['x']['all']].values})
    pixel_data.set_index('time', inplace=True)
    
    station_data_daily = station_data.resample('D').agg({f'{var}_{station_name}': tb.CERRA.AGGREGATION_RULES[var]})
    pixel_data_daily = pixel_data.resample('D').agg({f'{var}_cerra': tb.CERRA.AGGREGATION_RULES[var]})
    
    debias_data = station_data_daily.merge(pixel_data_daily, how = 'left', on = 'time')
    debias_data.dropna(inplace = True)
    debias_data.plot()
    
    print(f'>> build Debiaser - {method}')
    debiaser_ls = tb.generate_debiaser(data_ref = debias_data['2m_temperature_station'],
                                       data_raw = debias_data['2m_temperature_cerra'],               
                                       method = method)
    print('>> apply Debiaser')
    local_cerra.apply_debiaser(debiaser_ls, '2m_temperature',
                               save = debiased_cerra_file,
                               verbose = True)

    print('>> compare timeserie')
    local_cerra_file = f'Z:/_waterwise_data_process/_climate/_cerra_forecast/2m_temperature/2m_temperature_{site_id}.nc'  
    debiased_cerra_file = f'./output_debias_test/2m_temperature_{site_id}_debias.nc'   
    
    ws = tb.WeatherStation(station_name, station_path, variables = [var])
    station_data = ws._data[var]
    local_cerra  = tb.CERRA(local_cerra_file)   
    local_cerra_debiased = tb.CERRA(debiased_cerra_file)

    Y,X = pixel_ws['y']['all'],pixel_ws['x']['all']
    df_timeserie = pd.DataFrame({
        'time': local_cerra.dataset['time'].values,
         f'{var}_raw': local_cerra.dataset[var][:,Y,X].values,
         f'{var}_debiased': local_cerra_debiased.dataset[var][:,Y,X].values
         })
    df_timeserie.set_index('time', inplace = True)
    # print(df_timeserie)
    
    df_timeserie_daily = df_timeserie.resample('D').agg(
                            {f'{var}_raw': tb.CERRA.AGGREGATION_RULES[var],
                             f'{var}_debiased': tb.CERRA.AGGREGATION_RULES[var]})
    df_timeserie_daily = df_timeserie_daily.merge(station_data, how = 'left', on = 'time')
    df_timeserie_daily = df_timeserie_daily.drop('year', axis = 1)
    print(df_timeserie_daily)
  
    print('>> display timeserie')
    fig, ax = plt.subplots(1,1,figsize = [10,5])
    
    df_timeserie_daily.plot(ax=ax, y = f'{var}_station', color = 'blue', ls = '-', marker = 's', markersize = 1)
    df_timeserie_daily.plot(ax=ax, y = f'{var}_debiased', color = 'purple', ls = '-')
    df_timeserie_daily.plot(ax=ax, y = f'{var}_raw', color = 'grey', ls = ':')
    
    ax.set_xlim(['2013-01-01','2022-01-01'])


    fig, ax = plt.subplots(1,1,figsize = [10,10])
    ax.plot([-25,25],[-25,25],color = 'grey')
    df_timeserie_daily.plot(ax=ax, x = f'{var}_station', y = f'{var}_raw', color = 'blue', ls = '', marker = '.', markersize = 5)
    df_timeserie_daily.plot(ax=ax, x = f'{var}_station', y = f'{var}_debiased', color = 'purple', ls = '', marker = '.', markersize = 5)
    # df_timeserie_daily.plot(ax=ax, x = f'{var}_station', y = f'{var}_station', color = 'red', ls = '', marker = '.', markersize = 10)

    ax.set_xlim([-25,25])
    ax.set_ylim([-25,25])
    # print(local_cerra.dataset['2m_temperature'][:,Y,X].values)
    # print(local_cerra_debiased.dataset['2m_temperature'][:,Y,X].values)    
    for Y in range(local_cerra.shape_grid[0]):
        for X in range(local_cerra.shape_grid[1]):
            print(Y,X)
            df_timeserie = pd.DataFrame({
                'time': local_cerra.dataset['time'].values,
                 f'{var}_raw': local_cerra.dataset[var][:,Y,X].values,
                 f'{var}_debiased': local_cerra_debiased.dataset[var][:,Y,X].values
                 })
            df_timeserie.set_index('time', inplace = True)
            # print(df_timeserie)
            
            df_timeserie_daily = df_timeserie.resample('D').agg(
                                    {f'{var}_raw': tb.CERRA.AGGREGATION_RULES[var],
                                     f'{var}_debiased': tb.CERRA.AGGREGATION_RULES[var]})
            df_timeserie_daily = df_timeserie_daily.merge(station_data, how = 'left', on = 'time')
            df_timeserie_daily = df_timeserie_daily.drop('year', axis = 1)

            
            diffs = tb.evaluate_debias(df_timeserie_daily[f'{var}_station'],
                                df_timeserie_daily[f'{var}_raw'],
                                df_timeserie_daily[f'{var}_debiased'])
        
            df = pd.DataFrame({'raw': diffs['diff_raw_abs'], 'corr': diffs['diff_corr_abs']})
            print(df.mean())
            print(df_timeserie_daily.mean())


#%% test Timeserie stats

if testTimeserieStats:
    data_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/2m_temperature/2m_temperature_urse.nc'
    shape_path = 'Z:/HDPY_models/CR/20250410/_urse/results_stable/geographic/watershed.shp'
    output_path = './timeserie_statistic_test/'
    tb.create_folder(output_path)
    
    data = tb.CERRA(data_path)
    # print(data.dataset['2m_temperature'][:,:,:].values)
    stats = data.compute_timeserie_statistics(shape_path, 
                                              variable = '2m_temperature',
                                               catch_crs = 3035, save = False)
    
    # plot result
    fig, ax = plt.subplots(1,1,figsize = [10,5])

    stats.plot(ax = ax)
    
#%% test Climate stats and visualization
if testClimateStats:
    
    # data folders - files
    data_path_ = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/'
    data_path_ = f'{data_path_}_urse/_climate/_air_temperature/_reanalysis/_cerra_forecast/'
    data_path = f'{data_path_}2m_temperature_timeserie_statistics.csv'
    variable_id = '2m_temperature'
    location = 'urse'
    
    # fig folder
    fig_folder = './test_climate_stats/'
    tb.create_folder(fig_folder)
    
   
    # Load data
    stats = tb.ClimateStats(data_path, variable_id, location)
    
    # Climate strips plots   
    stats.plot_climate_stripes(fig_folder, display = True, verbose = True)
    stats.reset_data()
    
    # Temperature anomaly
    stats.plot_monthly_anomaly(fig_folder, display = True, verbose = True)
    
    # XY anomaly
    # data load 1
    data_path_ = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/'
    data_path_ = f'{data_path_}_urse/_climate/_total_precipitation/_reanalysis/_cerra_forecast/'
    data_path = f'{data_path_}total_precipitation_timeserie_statistics.csv'
    variable_id = 'total_precipitation'
    location = 'urse'   
    # Load data
    stats = tb.ClimateStats(data_path, variable_id, location)
   
    # dataload 2
    data2_path_ = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/'
    data2_path_ = f'{data2_path_}_urse/_climate/_air_temperature/_reanalysis/_cerra_forecast/'
    data2_path = f'{data2_path_}2m_temperature_timeserie_statistics.csv'
    variable_id2 = '2m_temperature'   
    # Load data
    stats2 = tb.ClimateStats(data2_path, variable_id2, location)
    
    df = tb.ClimateStats.plot_XY_anomaly(stats, stats2, fig_folder)

#%% PLAYGROUND

if 0:    
    # data folders - files
    data_path_ = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/'
    data_path_ = f'{data_path_}_urse/_climate/_total_precipitation/_reanalysis/_cerra_forecast/'
    data_path = f'{data_path_}total_precipitation_timeserie_statistics.csv'
    variable_id = 'total_precipitation'
    location = 'urse'
    
    # fig folder
    fig_folder = './test_climate_stats/'
    tb.create_folder(fig_folder)
    
   
    # Load data
    stats = tb.ClimateStats(data_path, variable_id, location)
    
    # # Climate strips plots   
    # stats.plot_climate_stripes(fig_folder, display = True, verbose = True)  
    
    # stats.data_origin.plot()
    # plt.xlim(['1985-01-25','1985-01-27'])
    
    # data folders - files
    data2_path_ = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/'
    data2_path_ = f'{data2_path_}_urse/_climate/_air_temperature/_reanalysis/_cerra_forecast/'
    data2_path = f'{data2_path_}2m_temperature_timeserie_statistics.csv'

    variable_id2 = '2m_temperature'

   
    # Load data
    stats2 = tb.ClimateStats(data2_path, variable_id2, location)
    
    df = tb.ClimateStats.plot_XY_anomaly(stats, stats2, fig_folder)
    
    
