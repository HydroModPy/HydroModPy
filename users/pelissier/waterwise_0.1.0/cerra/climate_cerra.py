"""
20260130

@author: delarueo
"""
#%%
from pathlib import Path
import cerra.toolbox_newFuns_cerra_dev as tb
import numpy as np
import pandas as pd
from waterwise.config import CerraParams
import geopandas as gpd
from shapely import Point
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

#%%
def make_local_mask( 
        workdir: Path, alps_grid_file : Path,  
        buffer: float, site_epsg : int, logger,
        checkplot: bool = False, reset: bool = True, 
        verbose: bool = False
        ):    

    # PAths to processing elements
    site_box_path = Path(workdir) / 'results_stable/geographic/box_buff.shp'
    site_mask_path = Path(workdir) / 'results_cerra/mask_box_buff.shp'

    # Check inputs
    if not site_box_path.exists():
        logger.info(f'ERROR | box_buffer.shp missing - run make_catchment Options')
        return False
    if not alps_grid_file.exists():
        logger.info(f'ERROR | cerra alps grid file missing')
        return False

    # Check for output directories - create if needed
    site_mask_path.parents[0].mkdir(parents = True, exist_ok = True)

    try:     
        grid = tb.CERRA(alps_grid_file) 
        mask = grid.do_site_mask(
                    site_box_path, 
                    site_mask_path, 
                    catch_crs = site_epsg,
                    verbose = verbose, 
                    checkplot = checkplot,  
                    save = True,
                    reset = reset,
                    buffer = buffer,
                    logger = logger
                    )              
        grid.__close__()
        logger.info(f'cerra site mask created - saved at {site_mask_path}')
    except:
        logger.info(f'ERROR | cerra site mask not created.')
        return False
    return mask

def make_local_cerra(
            mask: np.ndarray ,
            site_id: str,
            alps_forecast_dir: Path,
            alps_land_dir: Path,
            local_dir: Path,
            logger,
            years = [1984,2025],
            reset: bool = True,
            variables : dict = {
                'total_precipitation' : 'land',
                '2m_temperature': 'forecast',
                'surface_solar_radiation_downwards': 'forecast'
            },
            verbose = True
            ):
    # check and create output directory
    site_local_dir = local_dir / f'{site_id}' 
    site_local_dir.mkdir(parents = True, exist_ok = True)
    local_files = []
    for var_name,source_type in variables.items():
        if source_type == 'forecast':
            alps_path = alps_forecast_dir / var_name
        elif source_type == 'land':
            alps_path = alps_land_dir / var_name
        else:
            logger.error(f'{site_id} | invalided source type - Valid options: land forecast')
            continue       
        output_file = site_local_dir / f'{site_id}_{var_name}.nc'
        local_cerra_file, missing = tb.CERRA.extract_site_data(mask, 
                                    site_id, 
                                    alps_path, 
                                    [var_name], range(years[0],years[1]+1),
                                    output_file, 
                                    verbose = verbose,
                                    logger= logger)
        if missing == []:
            logger.info(f'{site_id} | {var_name} local netcdf {years}')
            logger.info(f'{site_id} | Saved at {output_file}')
        else:
            logger.info(f'{site_id} | {var_name} local netcdf {years}')
            logger.info(f'{site_id} | Saved at {output_file}')
            logger.warning(f'{site_id} | missing years {missing}')
        local_files.append(local_cerra_file)
    return local_files

def make_pyhelp_inputs(
                site_id:str,
                grid_file:Path,
                local_dir:Path,
                pyhelp_dir:Path,
                params:CerraParams,
                logger = False,
                variables = [
                        '2m_temperature',#: 'forecast',
                        'surface_solar_radiation_downwards',#: 'forecast',
                        'total_precipitation', # : 'land',                        
                ],                
                verbose = True,
                checkplot = True,
                newGrid = False
                ):                

    ## manage_grid()
    # pyHelp grid management
    if not newGrid:
        try: 
            logger.info(f'{site_id} | load pyhelp grid from base file')
            gdf_helpGrid, df_helpGrid = tb.Geo.load_pyHelpGrid(grid_file, verbose = verbose)                      
        except:
            logger.info('ERROR | Fail to read provide grid file - safety mode : create new grid.')
            newGrid = True

    # if necessary create a new pyHelp grid
    if newGrid:
        # Define & create output folder
        try:
            var_name = variables[0]
            local_cerra_file = local_dir / f'{site_id}/{site_id}_{var_name}.nc'
            if local_cerra_file.exists():
                data = tb.CERRA(local_cerra_file)
            else:
                logger.info(f'ERROR | CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
                return False
                        
            logger.info(f'{site_id} | generate pyhelp grid from cerra local file')
            # open cerra grid as a GeoDataFrame and find internal bounds
            gdf_cerraGrid, yx_cerraGrid, df_yx_cerraGrid = data._extract_gdfGrid()
            bounds = tb.Geo.calculate_internal_bounds(gdf_cerraGrid, shrink_distance = 0.1)  
            # Generate the grid from local cerra grid and processing parameters
            gdf_helpGrid, df_helpGrid = data.create_pyHelpGrid(bounds, params.spacestep_meter)
            newGrid = False
            logger.info(f'{site_id} | pyhelp grid created') 
            
            if checkplot:
                logger.info(f'{site_id} | checkplot pyhelp and cerra grid')
                gdf_cerraGrid = gdf_cerraGrid.set_crs('EPSG:4326', allow_override=True)
                gdf_helpGrid = gdf_helpGrid.set_crs('EPSG:4326', allow_override=True)
                tb.Geo.plot_multiple_gdfs([gdf_cerraGrid, gdf_helpGrid], 
                                        title ='Pixel centers of the grids', 
                                        labels = ['cerra','pyhelp'], markersize = [100,10])
        except:
            logger.info(f'ERROR | Fail to create pyhelp grid.') 
            return False
    
    ## generate_pyhelp_input
        # Generate pyHelp input file on the defined grid
    logger.info(f'{site_id} | generate pyhelp inputs from local cerra file')
    # Define & create output folder
    output_folder = pyhelp_dir / f'{site_id}'
    output_folder.mkdir(parents = True, exist_ok = True)
    for var_name in variables:                    
        logger.info(f'{site_id} | generate pyhelp - {var_name}') 

        local_cerra_file = local_dir / f'{site_id}/{site_id}_{var_name}.nc'
        output_file = output_folder / f'{site_id}_{var_name}_pyhelp.csv'
        if local_cerra_file.exists():
            data = tb.CERRA(local_cerra_file)
            logger.info(f'{site_id} | load local cerra') 
        else:
            logger.error(f'{site_id} | CERRA file not found at {local_cerra_file} - Go to create local cerra.') 
            return False
        result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var_name, 
                                        rule = params.interpolation_rule, timestep = params.timestep, 
                                        logger = logger,
                                        verbose = verbose,
                                        save = output_file)      
        logger.info(f'{site_id} | Saved at {output_file}')
                
    logger.info(f'{site_id} | all pyhelp inputs generated')
    return True
    try:                
        # Generate pyHelp input file on the defined grid
        logger.info(f'{site_id} | generate pyhelp inputs from local cerra file')
        # Define & create output folder
        output_folder = pyhelp_dir / f'{site_id}'
        output_folder.mkdir(parents = True, exist_ok = True)
        for var_name in variables:                    
            logger.info(f'{site_id} | generate pyhelp - {var_name}') 

            local_cerra_file = local_dir / f'{site_id}/{site_id}_{var_name}.nc'
            output_file = output_folder / f'{site_id}_{var_name}_pyhelp.csv'
            if local_cerra_file.exists():
                data = tb.CERRA(local_cerra_file)
                logger.info(f'{site_id} | load local cerra') 
            else:
                logger.error(f'{site_id} | CERRA file not found at {local_cerra_file} - Go to create local cerra.') 
                return False
            logger.info(f'{site_id} | test') 
            result = data.generate_pyHelp_file(gdf_helpGrid, df_helpGrid, var_name, 
                                            rule = params.interpolation_rule, timestep = params.timestep, 
                                            verbose = verbose,
                                            save = output_file)      
            logger.info(f'{site_id} | Saved at {output_file}')
                    
        logger.info(f'{site_id} | all pyhelp inputs generated')
        return True
    except:
        logger.error(f'{site_id} | fail to generate pyhelp inputs')
        return False
    
def make_local_csv(site_id: str,
                local_dir: Path,
                variables, # 'total_precipitation','surface_solar_radiation_downwards'],
                logger,
                checkplot:bool = False,
                shape = False,
                timeserie_dir: Path = False
                ):

    
    # check (& create) ouput folder
    site_local_dir = local_dir / f'{site_id}' 
    site_local_dir.mkdir(parents = True, exist_ok = True)
    if timeserie_dir:
        site_timeserie_dir = timeserie_dir / f'{site_id}' 
        site_local_dir.mkdir(parents = True, exist_ok = True)

    logger.info(f'{site_id} | make local csv ')

    list_csvs = []
    for var_name in variables:
        logger.info(f'{site_id} | {var_name}')
        local_cerra_file = site_local_dir / f'{site_id}_{var_name}.nc'
        if local_cerra_file.exists():
                data = tb.CERRA(local_cerra_file)
        else:
            logger.error(f'{site_id} | CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
            continue

        timeseries = pd.DataFrame({'time': data.dataset.time})
        df_loc = pd.DataFrame(columns = ['lon', 'lat'], index = [f'{y}.{x}' for y in data.dataset.y.values for x in data.dataset.x.values])
        latitudes = data.dataset.latitude.values
        longitudes = data.dataset.longitude.values
        for y in data.dataset.y.values:
            for x in data.dataset.x.values:
                timeseries[f'{y}.{x}'] = pd.to_numeric(data.dataset[var_name].sel(y=y, x=x).to_series().values)
                df_loc.at[f'{y}.{x}', 'lon'] = longitudes[y,x]
                df_loc.at[f'{y}.{x}', 'lat'] = latitudes[y,x]

        # organise timeseries pixel timeserie      
        timeseries['time'] = pd.to_datetime(timeseries['time'])
        timeseries.set_index('time', inplace = True)
        # organise pixel localisation information
        gdf = gpd.GeoDataFrame(df_loc, geometry = [Point(row['lon'], row['lat']) for i,row in df_loc.iterrows()], crs="EPSG:4326")
        
        # save extracted data 
        ts_file = site_local_dir / f'{site_id}_{var_name}.csv'
        timeseries.to_csv(ts_file, sep = ',')
        list_csvs.append(ts_file)

        geo_file = site_local_dir / f'{site_id}_pixel_loc.shp'
        gdf.to_file(geo_file)
        # checplot
        if checkplot:
            # Plot 1 - Time Series
            fig, ax = plt.subplots(figsize=(10, 5))
            colors = plt.cm.rainbow(np.linspace(0, 1, timeseries.shape[1]))
            i = 0
            for col in timeseries.columns:
                if col != 'time':
                    timeseries.plot(ax=ax, y=col, label=col, color=colors[i])
                    i += 1

            # Formatting y-axis ticks to two decimal places
            ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f'))

            # Adjusting legend with specific number of rows and columns
            ncols = 4
            nrows = (len(timeseries.columns) - 1 + ncols - 1) // ncols
            ax.legend(ncols=ncols, bbox_to_anchor=(1.05, 1 - (nrows * 0.1)), loc='upper left')
            plt.title('Time Series Plot')
            plt.xticks(rotation=45)  # Rotate x-ticks if necessary

            # Plot 2 - Location
            fig, ax = plt.subplots(figsize=(10, 10))
            i = 0
            for idx, row in gdf.iterrows():
                ax.scatter(row['lon'], row['lat'], label=idx, color=colors[i])
                i += 1

            if shape:
                shp = gpd.read_file(shape)
                shp = gpd.GeoDataFrame(shp['geometry'])
                shp.set_crs(epsg = 3035)
                shp.to_crs(4326, inplace = True)
                shp.plot(ax=ax, alpha = 0.1, label = 'AoI')       

            # Formatting x and y-axis ticks to two decimal places
            ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f'))  # Longitude
            ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f'))  # Latitude

            # Adjust legend for the location plot with similar configuration
            ax.set_xlabel('Longitude')
            ax.set_ylabel('Latitude')

            ax.legend(ncols=ncols, bbox_to_anchor=(1.05, 1 - (nrows * 0.1)), loc='upper left')  # Adjust location
            plt.title('Location Plot')        

        if timeserie_dir:            
            timeserie_file = site_timeserie_dir / f'{site_id}_{var_name}_timeserie.csv'
            data.compute_timeserie_statistics(variable = var_name,
                                            save = timeserie_file,
                                            site_id = site_id,
                                            shape_path = shape,
                                            logger = logger,
                                            checkplot= checkplot)      

    return list_csvs, gdf

    
    
    
# # %%
# def make_climate_timeserie(
#     site_id: str,
#     local_dir: Path,
#     timeserie_dir: Path,
#     logger,   
#     variables = [
#         '2m_temperature',
#         'total_precipitation',
#         'surface_solar_radiation_downwards',
#         # ...
#     ],      
#     shape_path = False, # if provide shape - stats only on pixels on shape (area ratio)
#     checkplot = True):
#         # check and create output directory
#         site_timeserie_dir = timeserie_dir / f'{site_id}' 
#         site_timeserie_dir.mkdir(parents = True, exist_ok = True)

#         for var_name in variables:
#             local_cerra_file = local_dir / f'{site_id}/{site_id}_{var_name}.nc'
#             if local_cerra_file.exists():
#                 data = tb.CERRA(local_cerra_file)
#             else:
#                 logger.error(f'CERRA file not found at {local_cerra_file}. Go to create local cerra.') 
#                 return False

#         # define output location            
#         timeserie_file = site_timeserie_dir / f'{site_id}_{var_name}_timeserie.csv'
#         logger.info(f'{site_id} | {var_name} create timeserie statistics')
#         stats = data.compute_timeserie_statistics(variable = var_name,
#                                                 save = timeserie_file,
#                                                 site_id = site_id,
#                                                 shape_path = shape_path,
#                                                 logger = logger,
#                                                 checkplot= checkplot)                

