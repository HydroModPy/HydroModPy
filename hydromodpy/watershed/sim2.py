# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import sys
import os
from os.path import dirname, abspath
import re
import requests
from io import BytesIO
import gzip

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import mapping
import rasterio as rio
import rasterio.features # necessary to avoid a bug
import xarray as xr
xr.set_options(keep_attrs = True)

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox, get_logger
from hydromodpy.modeling import netcdf

logger = get_logger(__name__)

#%% CLASS

class Sim2:
    """
    Class to extract the SIM2 historic reanalysis data.
    Since 13/12/2023 these data are in open access on https://meteo.data.gouv.fr/
    (tab "Données climatologiques de référence pour le changement climatique",
     then "Données changement climatique - SIM quotidienne" : 
     https://meteo.data.gouv.fr/datasets/6569b27598256cc583c917a7 )
        
    Note: Data values stored in HydroModPy variables are reprojected and 
    selected according to user requirements (period, time_step, ...) but
    generated netcdf files are kept in original data spatial profile.
    """
    
    def __init__(self, *,
                 var_list, nc_data_path: str,
                 first_year: int, last_year: int=None,
                 time_step: str, sim_state: str,
                 spatial_mean=False, geographic, 
                 disk_clip: str=None):
        """
        Parameters
        ----------
        var_list : iterable
            List of variable names.
            HydroModPy variable names: 'recharge' | 'runoff' | 'evt' | 'precip' | 'temp'
            Also works with SIM2 variable names: 'DRAINC' | 'RUNC' | 'EVAP' | 'PRETOT' | 'T' ...
        nc_data_path : str
            Path to the folder containing the clipped SIM2 .nc files.
        first_year : int
            Data will be extracted from 1st January of first_year to 31st December of last_year.
        last_year : int or None (optional)
            End date of data to be extracted. 
            If None, the current date will be used instead.
        time_step : str
            'D' for daily
            'W' for weekly (aggregated on Sundays)
            'M' for monthly (aggregated on last day of the month)
            ...for offset alias list, see https://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#offset-aliases 
        sim_state : str
            'transient' | 'steady'
            If 'steady', the time mean will be used.
        spatial_mean : bool
            False (default). If True, data will be spatially averaged and returned
            as a pandas.DataFrame instead of an xarray.DataSet.
        geographic : object
            Watershed.geographic object including infos such as crs, mask...
        disk_clip : str
            Shapefile path or flag ('watershed' | None) to indicate how to clip
            the netcdf files that are stored on the nc_data_path folder.
            The only purpose of clipping these files is to save disk space

        Returns
        -------
        None. The sim2 object is updated. 
        Also create or update the netcdf files.

        """
        
        logger.info("Extracting SIM2 climatic datasets from remote archives")
        
        # ---- Initialization
        self.var_list = var_list
        self.var_sublist = []
        self.nc_data_path = nc_data_path
        if not os.path.isdir(self.nc_data_path):
            os.makedirs(self.nc_data_path)
        self.first_date = pd.to_datetime(f"{first_year}-01-01", format = "%Y-%m-%d")
        if last_year is None:
            self.last_date = pd.to_datetime('today').normalize()
        else:
            self.last_date = pd.to_datetime(f"{last_year}-12-31", format = "%Y-%m-%d")
        self.time_step = time_step
        self.sim_state = sim_state
        self.spatial_mean = spatial_mean
        self.geographic = geographic
        self.values = {}
        self.raw_values = {} # unformatted xarray.Datasets
        self.final_filelist = {}
        if disk_clip == 'watershed':
            self.clip_mask = self.geographic.watershed_box_shp
        elif disk_clip is None:
            self.clip_mask = None
        else:
            if os.path.splitext(disk_clip)[-1] == '.shp':
                self.clip_mask = disk_clip
            else:
                logger.error("disk_clip must reference a .shp file or use 'watershed'/'False' flags")
                return
        
        varnames_dict = {
        'DRAINC': 'recharge',
        'RUNC': 'runoff',
        'EVAP': 'evt',
        'PRETOT': 'precip',
        'PRENEI': 'snow',
        'PRELIQ': 'rain',
        'T': 't',
        'FF': 'wind',
        'SWI': 'swi',
        'ETP': 'etp',
        'TINF_H': 'tmin',
        'TSUP_H': 'tmax',
        'SSI': 'ssi',
        'DLI': 'dli',
        'PE': 'eff_rain',
        'WG_RACINE': 'wg_root',
        'WGI_RACINE': 'wgi_root',
        'Q': 'hum_spec',
        'HU': 'hum_rel',
        'RESR_NEIGE': 'snow_resr',
        'RESR_NEIGE6': 'snow_resr_6utc',
        'HTEURNEIGE': 'snow_thickness',
        'HTEURNEIGEX': 'snow_thickness_max',
        'HTEURNEIGE6': 'snow_thickness_6utc',
        'SNOW_FRAC': 'snow_cover',
        'ECOULEMENT': 'snow_flow',
        'SSWI_10J': 'soil_drought_index',
        }
        self.HyMoPy_var_by_sim_var = pd.DataFrame.from_dict(
            data = varnames_dict,
            orient = 'index',
            columns = ['HyMoPy_var'])
        self.sim_var_by_HyMoPy_var = pd.DataFrame(
            index = self.HyMoPy_var_by_sim_var.HyMoPy_var.copy(),
            columns = ['sim_var'],
            data = self.HyMoPy_var_by_sim_var.index.copy())
        
        
        # ---- Determine which data needs to be downloaded
        # Data already available for each variable 
# =============================================================================
#         self.nc_file_by_var = dict.fromkeys(var_list, None)
#         self.start_date_by_var = dict.fromkeys(var_list, None)
#         self.end_date_by_var = dict.fromkeys(var_list, None)
# =============================================================================
        self.local_data = pd.DataFrame(index = var_list, columns = ['nc_file',
                                                                    'start_date',
                                                                    'end_date',
                                                                    'extent'])
        self.local_data.extent = False

        sim_pattern = re.compile('.*_SIM2_')
        # year_pattern = re.compile('\d{4,8}')
        filelist = [os.path.join(self.nc_data_path, f) \
                    for f in os.listdir(self.nc_data_path) \
                        if os.path.isfile(os.path.join(self.nc_data_path, f))]
        if len(filelist) > 0: # folder is not empty
            for file in filelist:
                filename = os.path.split(file)[-1]
                sim_match = sim_pattern.findall(filename)
                # years = year_pattern.findall(filename)
                if (len(sim_match) > 0) & (os.path.splitext(file)[-1] == '.nc'):
                    sim_var = sim_match[0][0:-6]
                    var = self.HyMoPy_var_by_sim_var.loc[sim_var, 'HyMoPy_var']
                    self.local_data.loc[var, 'nc_file'] = file
                    # if len(years[0]) == 4:
                    #     date_i = pd.to_datetime(f"{years[0]-01-01}", format = "%Y-%m-%d")
                    # self.dates_by_var[self.HyMoPy_var_by_sim_var[sim_var]] = date_i
                    
                    remove_file = False
                    with xr.open_dataset(file, decode_coords = 'all', decode_times = True) as ds_temp:
                        # Dates
                        if pd.date_range(start = ds_temp.time[0].item(), 
                                         end = ds_temp.time[-1].item(), 
                                         freq = 'D').size == ds_temp.time.size: # all time values are contiguous
                            self.local_data.loc[var, 'start_date'] = pd.to_datetime(ds_temp.time[0].item())
                            self.local_data.loc[var, 'end_date'] = pd.to_datetime(ds_temp.time[-1].item())
                        # Spatial extent
                        resolution = abs(ds_temp.rio.transform()[0])
                        ds_extent = np.array(ds_temp.rio.bounds())
                        if self.clip_mask is not None:
                            mask = gpd.read_file(self.clip_mask)
                            mask_extent = mask.buffer(resolution).total_bounds
                        else:
                            mask_extent = (56000.0, 1613000.0, 1200000.0, 2685000.0) # whole France
                        
                        if (ds_extent[0:2] <= mask_extent[0:2]).any() | (ds_extent[2:4] >= mask_extent[2:4]).any() :
                            self.local_data.loc[var, 'extent'] = True
                        else:
                            logger.warning(
                                "Local dataset %s does not cover requested spatial extent",
                                os.path.split(file)[-1],
                            )
                            remove_file = True # the file will be deleted (outside this 'with' section)
                    
                    if remove_file:
                        os.remove(file)
                            
            self.local_data.iloc[:, 0:3][self.local_data.extent == True] = np.nan
        
        # ---- Download
        self.download()
        
        
        # ---- Clip data
        # Convert HyMoPy var list ('recharge', 'runoff'...) into sim var list ('DRAINC', 'RUNC'...)
        sim_varlist = self.sim_var_by_HyMoPy_var.loc[self.var_list].sim_var.values
        
        if self.clip_mask is not None:
            self.clip_folder(self.nc_data_path, 
                              self.clip_mask,
                              sim_varlist)            
        
        # ---- Merge NetCDF files
        self.merge_folder(self.nc_data_path, sim_varlist)
        
        # ---- Format result for HydroModPy
        logger.info("Formatting SIM2 results for HydroModPy")
        for var in self.final_filelist:
            logger.info("Processing SIM2 variable %s", var)
            # Refine period with accurate user dates
            logger.debug("Refining period for %s", var)
            self.values[var] = self.raw_values[var].loc[
                {'time' : slice(self.first_date, self.last_date)}]
            # Apply sim_stat option
            if self.sim_state == 'steady':
                logger.debug("Simplifying time dimension for %s", var)
                self.values[var] = self.values[var].mean(dim = 'time')
            # Reprojection
            logger.debug("Reprojecting %s to model grid", var)
            self.values[var].rio.write_crs(rio.crs.CRS.from_epsg(27572), inplace = True)
            self.values[var] = toolbox.load_to_xarray(
                # self.final_filelist[var],
                self.values[var],
                base_path = self.geographic.watershed_box_buff_dem,
                dst_crs = self.geographic.crs_proj)
            mask, _, _, _ = toolbox.load_to_numpy(self.geographic.watershed_dem,
                                                       dst_crs = self.geographic.crs_proj) 
            encodings = self.values[var][self.sim_var_by_HyMoPy_var.loc[var, 'sim_var']].encoding
            self.values[var] = self.values[var].where(mask != self.geographic.nodata)
            self.values[var][self.sim_var_by_HyMoPy_var.loc[var, 'sim_var']].encoding = encodings
            # Apply spatial_mean option:
            if self.spatial_mean == True:
                logger.debug("Reducing spatial dimensions for %s", var)
                self.values[var] = self.values[var].drop('spatial_ref').mean(dim = ['x', 'y']).to_pandas() # convert xr.Dataset to pd.Dataframe
                # convert pd.Dataframe to pd.Series or to single value:
                if self.sim_state == 'transient':
                    self.values[var] = self.values[var].iloc[:, 0]
                elif self.sim_state == 'steady':
                    self.values[var] = self.values[var].iloc[0]
                # Otherwise instead of .iloc[:,0]: self.values[var] = self.values[var][self.sim_var_by_HyMoPy_var.loc[var, 'sim_var']] 
            # Apply timestep
            if (self.sim_state == 'transient') & (self.time_step != 'D'):
                logger.debug("Resampling %s to %s", var, self.time_step)
                if self.spatial_mean == False:
                    self.values[var] = self.values[var].resample(time = self.time_step).mean(dim = 'time')
                    self.values[var][self.sim_var_by_HyMoPy_var.loc[var, 'sim_var']].encoding = encodings
# =============================================================================
#                     # Very slow. Attempt to have a quicker resolution:
#                     temp_df = self.values[var].to_dataframe().reset_index([1,2]).resample(self.time_step).mean()
#                     temp_df.reset_index()
#                     self.values[var] = temp_df.set_index(['time', 'y', 'x']).to_xarray()
# =============================================================================
                elif self.spatial_mean == True:
                    self.values[var] = self.values[var].resample(self.time_step).mean()
            
            
        

    #%% Download                
    def download(self):
        """
        Download only the necessary data files from MeteoFrance API
        """
        # Until the access to SIM2 data is implemented through the Météo-France's
        # API (https://portail-api.meteofrance.fr), the current stable urls
        # are used.
        
        stable_urls = {
            'QUOT_SIM2_1958-1959': ('https://www.data.gouv.fr/fr/datasets/r/5dfb33b3-fae5-4d0e-882d-7db74142bcae', 
                                    0.16, pd.to_datetime('1958-08-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('1959-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_1960-1969': ('https://www.data.gouv.fr/fr/datasets/r/eb0d6e42-cee6-4d7c-bc5b-646be4ced72e', 
                                    1.1, pd.to_datetime('1960-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('1969-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_1970-1979': ('https://www.data.gouv.fr/fr/datasets/r/33417617-c0dd-4513-804e-c3f563cb81b4', 
                                    1.1, pd.to_datetime('1970-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('1979-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_1980-1989': ('https://www.data.gouv.fr/fr/datasets/r/08ad5936-cb9e-4284-a6fc-36b29aca9607', 
                                    1.1, pd.to_datetime('1980-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('1989-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_1990-1999': ('https://www.data.gouv.fr/fr/datasets/r/ad584d65-7d2d-4ff1-bc63-4f93357ed196', 
                                    1.1, pd.to_datetime('1990-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('1999-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_2000-2009': ('https://www.data.gouv.fr/fr/datasets/r/10d2ce77-5c3b-44f8-bb46-4df27ed48595', 
                                    1.1, pd.to_datetime('2000-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('2009-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_2010-2019': ('https://www.data.gouv.fr/fr/datasets/r/da6cd598-498b-4e39-96ea-fae89a4a8a46', 
                                    1.1, pd.to_datetime('2010-01-01', format = "%Y-%m-%d"),
                                    pd.to_datetime('2019-12-31', format = "%Y-%m-%d")),
            'QUOT_SIM2_latest_period': ('https://www.data.gouv.fr/fr/datasets/r/92065ec0-ea6f-4f5e-8827-4344179c0a7f', 
                                        1.1, pd.to_datetime('2020-01-01', format = "%Y-%m-%d"),
                                        (pd.to_datetime('today').normalize() - pd.Timedelta(1, 'D')).replace(day = 1) - pd.Timedelta(1, 'D')),
            'QUOT_SIM2_latest_days': (#'https://www.data.gouv.fr/fr/datasets/r/ff8e9fc6-d269-45e8-a3c3-a738195ea92a',
                                      'https://www.data.gouv.fr/fr/datasets/r/adcca99a-6db0-495a-869f-40c888174a57',
                                       0.1, (pd.to_datetime('today').normalize() - pd.Timedelta(1, 'D')).replace(day = 1),
                                       pd.to_datetime('today').normalize() - pd.Timedelta(1, 'D')),
            }
        
        self.available_data = pd.DataFrame.from_dict(
            data = stable_urls, 
            orient = 'index', 
            columns = ['url', 'size_Go', 'start_date', 'end_date'])
        
        # ---- Identify which files will be needed
        # If there is no netcdf file already
        if self.local_data.nc_file.isnull().values.any():
            # Then all the data files will be downloaded
            to_download = self.available_data.index[
                (self.available_data.end_date > self.first_date) \
                     & (self.available_data.start_date < self.last_date)]
        else:
            # The "core period" is the period that is covered by local data for 
            # specified variables
            min_core_date = self.local_data.start_date[self.var_list].max()
            max_core_date = self.local_data.end_date[self.var_list].min()
            to_download = self.available_data.index[
                ((self.available_data.start_date < min_core_date) & (self.available_data.end_date > self.first_date)) \
                    | ((self.available_data.end_date > max_core_date) & (self.available_data.start_date < self.last_date))]
        
        # Files to download to cover the times
        # (Note that if the specified spatial extent is not covered, the files have been previously deleted in __init__())
        if len(to_download) > 0:
            datasets_info = ', '.join(
                [
                    f"{dataname} ({self.available_data.loc[dataname, 'size_Go']})"
                    for dataname in to_download
                ]
            )
            logger.info("The following .csv datasets will be downloaded: %s", datasets_info)
            ram_space = self.available_data.loc[to_download, 'size_Go'].max()
            disk_space = self.available_data.loc[to_download, 'size_Go'].sum()/2.5*len(self.var_list) \
                - sum(os.path.getsize(os.path.join(self.nc_data_path, f)) \
                      for f in os.listdir(self.nc_data_path) \
                          if os.path.isfile(os.path.join(self.nc_data_path, f)))/1073741824 
            disk_space = np.max([0, disk_space])
            logger.info(
                "Downloading %s datasets to cover requested period and area",
                ", ".join(to_download),
            )
            logger.info(
                "Estimated resources: RAM < %.2f GB, disk < %.2f GB",
                ram_space,
                disk_space,
            )
          
        # ---- Download the required files
        if len(to_download) > 0:
            for dataname in to_download: 
                logger.info("Downloading dataset %s", dataname)
                logger.debug("Download may take several minutes depending on bandwidth")
                response = requests.get(self.available_data.loc[dataname, 'url'])
        
                if response.status_code == 200:
                    # Decompress gzip content
                    with gzip.open(BytesIO(response.content), 'rt') as f:
                        # Determine variables to extract in the current file
                        self.var_sublist = self.local_data.loc[self.var_list].index[
                            (self.local_data.start_date[self.var_list] > self.available_data.loc[dataname, 'start_date']) \
                                | (self.local_data.end_date[self.var_list] < self.available_data.loc[dataname, 'end_date'])]
                        self.var_sublist = self.var_sublist.to_list() + self.local_data[self.local_data.nc_file.isnull()].index.to_list()
                        # Replace 'precip' with 'rain' and 'snow'
                        if len(set(self.var_sublist).intersection(['precip'])) > 0:
                            self.var_sublist = set(self.var_sublist) - set(['precip'])
                            self.var_sublist = list(self.var_sublist.union(['rain', 'snow']))    
                        # Read .csv file and export to .nc files (one for each variable)
                        self.to_netcdf(f, dataname)         
                else:
                    logger.error("Failed to download %s.csv (status %s)", dataname, response.status_code)
                    
        else:
            logger.info("Existing SIM2 CSV datasets already cover requested domain and period")
                
        
    
    #%% Convert to NetCDF
    def to_netcdf(self, csv_file, dataname):  
        # root_folder = os.path.split(os.path.split(csv_file_path)[0])[0]
    # =============================================================================
    #     coords_filepath = os.path.join(
    #         root_folder, 'coordonnees_grille_safran_lambert-2-etendu.csv')
    # =============================================================================

        # Needed columns
        usecols = ['LAMBX', 'LAMBY', 'DATE']
    
        # Units and long names (updated according to SIM2 new specifications from Météo-France)
        units_by_var = {
                     'PRENEI': ['mm', 'Précipitations solides cumul quotidien ]06UTC-06UTC]'],
                     'PRELIQ': ['mm', 'Précipitations liquides cumul quotidien ]06UTC-06UTC]'],
                     'T': ['°C','Température moyenne quotidienne ]00UTC-00UTC]'],
                     'FF': ['m/s', 'Vent moyenne quotidienne ]00UTC-00UTC]'],
                     'Q': ['g/kg','Humidité spécifique moyenne quotidienne ]00UTC-00UTC]'],
                     'DLI': ['J/cm2', 'Rayonnement atmosphérique cumul quotidien ]00UTC-00UTC]'],
                     'SSI': ['J/cm2', 'Rayonnement visible cumul quotidien ]00UTC-00UTC]'],
                     'HU': ['%', 'Humidité relative moyenne quotidienne ]00UTC-00UTC]'],
                     'EVAP': ['mm', 'Evapotranspiration totale cumul quotidien ]06UTC-06UTC]'],
                     'ETP': ['mm', 'Evapotranspiration potentielle (formule de Penman-Monteith)'],
                     'PE': ['mm', 'Pluies efficaces cumul quotidien ]06UTC-06UTC]'],
                     'SWI': ['%', "Indice d'humidité des sols moyenne quotidienne [06UTC-06UTC]"],
                     'DRAINC': ['mm', 'Drainage cumul quotidien ]06UTC-06UTC]'],
                     'RUNC': ['mm', 'Ruissellement cumul quotidien ]06UTC-06UTC]'],
                     'RESR_NEIGE': ['mm', 'Equivalent en eau du manteau neigeux moyenne quotidienne [06UTC-06UTC]'],
                     'RESR_NEIGE6': ['mm', 'Equivalent en eau du manteau neigeux à 06 UTC'],
                     'HTEURNEIGE': ['m', 'Epaisseur du manteau neigeux moyenne quotidienne [06UTC-06UTC]'],
                     'HTEURNEIGE6': ['m', 'Epaisseur du manteau neigeux à 06 UTC'],
                     'HTEURNEIGEX': ['m', 'Epaisseur du manteau neigeux horaire maximum au cours de la journée'],
                     'SNOW_FRAC': ['%', 'Fraction de maille recouverte par la neige moyenne quotidienne [06UTC-06UTC]'],
                     'ECOULEMENT': ['mm', 'Ecoulement à la base du manteau neigeux cumul quotidien ]06UTC-06UTC]'],
                     'WG_RACINE': ['m³/m³','Contenu en eau liquide dans la couche racinaire à 06 UTC'],
                     'WGI_RACINE': ['m³/m³', 'Contenu en eau gelée dans la couche racinaire à 06 UTC'],
                     'TINF_H': ['°C', 'Température minimale des 24 températures horaires période ]18UTC-18UTC]'],
                     'TSUP_H': ['°C', 'Température maximale des 24 températures horaires période ]06UTC-06UTC]'],
                     'PRETOT': ['mm', 'Précipitations totales (cumul quotidien 06-06 UTC)'],
                     'SSWI_10J': ['sans unité', 'indice sécheresse de l\'humidité des sols intégré sur 10 jours'],
                     }
        # NB: Cumulated values (day 1) are summed from 06:00 UTC (day 1) to 06:00 UTC (day 2)
        # Therefore, days correspond to Central Standard Time days.
    
        #%%% Loading
        logger.info("Loading SIM2 CSV file into DataFrame")
        logger.debug("This step can take more than one minute per parameter for decade-scale datasets")
        
        df = pd.read_csv(csv_file, sep=';', 
                         usecols=usecols + self.sim_var_by_HyMoPy_var.loc[self.var_sublist, 'sim_var'].to_list(),
                         header=0, decimal='.',
                         parse_dates=['DATE'],
                         # date_format='%Y%m%d', # Not available before pandas 2.0.0
                         )
        
        #%%% Formatting    
        df.rename(columns = {'LAMBX': 'x', 'LAMBY': 'y', 'DATE': 'time'}, inplace = True)
        df[['x', 'y']] = df[['x', 'y']]*100 # convert hm to m
        df.set_index(['time', 'y', 'x'], inplace = True)
        
        # Add new quantities if needed
        if ('PRENEI' in df.columns) & ('PRELIQ' in df.columns):
            df['PRETOT'] = df['PRENEI'] + df['PRELIQ']
            logger.debug("Computed PRETOT as PRENEI + PRELIQ")
            
        ds = df.to_xarray()
        # Continuous axis
        ds = ds.reindex(x = range(ds.x.min().values, ds.x.max().values + 8000, 8000))
        ds = ds.reindex(y = range(ds.y.min().values, ds.y.max().values + 8000, 8000))
        # Include CRS
        ds.rio.write_crs(27572, inplace = True)
        # Standard attributes
        ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                      'long_name': 'x coordinate of projection',
                      'units': 'Meter'}
        ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                      'long_name': 'y coordinate of projection',
                      'units': 'Meter'}
        
        #%%% Export 
        logger.info("Exporting SIM2 variables to NetCDF")
# =============================================================================
#         if not os.path.exists(os.path.join(self.nc_data_path, "temp_netcdf_indiv")):
#             os.mkdir(os.path.join(self.nc_data_path, "temp_netcdf_indiv"))
# =============================================================================
        
        for var in list(ds.data_vars): # batch_var: 
            # Include metadata
            ds[var].attrs = {'standard_name': var,
                             'long_name': units_by_var[var][1],
                             'units': units_by_var[var][0]}
            
            ds_var = ds[[var]]
            
            csv_name = os.path.splitext(os.path.split(dataname)[-1])[0].replace('QUOT_', '')
            
            ds_var.to_netcdf(os.path.join(self.nc_data_path, '_'.join([var, csv_name]) + '.nc'))     
            logger.info("Exported %s to NetCDF", var)

    
    #%% Convert whole folder to netcdf
    def folder_to_netcdf(self, folder):
        """
        Parameters
        ----------
        folder : str
            Folder containing the .csv files.
    
        Returns
        -------
        None. Creates the .nc files in the folder 'netcdf'
    
        """
        
        filelist = [f for f in os.listdir(folder) 
                    if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.csv')]
        
        for f in filelist:
            filename = os.path.splitext(f)[0]
            sim_pattern = re.compile('SIM2_')
            years = sim_pattern.split(filename)[-1]
            logger.info("Converting SIM2 CSV slice %s", years)
            self.to_netcdf(os.path.join(folder, f))
        
    
    #%% Merge
    def merge(self, filelist):
        root_folder = os.path.split(filelist[0])[0]
        
        sim_pattern = re.compile('.*_SIM2_')
        filename = os.path.split(os.path.splitext(filelist[0])[0])[-1]
        sim_var = sim_pattern.findall(filename)[0][0:-6]
        HyMoPy_var = self.HyMoPy_var_by_sim_var.loc[sim_var].item()
        
        logger.info("Merging %s (%s) NetCDF files", sim_var, HyMoPy_var)
        
        with xr.open_dataset(
                filelist[0], decode_coords = 'all', decode_times = True) as ds_merged:
            ds_merged.load() # to unlock the resource
        logger.debug("Base file for merge: %s", os.path.split(filelist[0])[-1])
        
        encod = ds_merged[list(ds_merged.data_vars)[0]].encoding
        
        for f in filelist[1:]:
            with xr.open_dataset(
                    f, decode_coords = 'all', decode_times = True) as ds:
                ds_merged = ds.combine_first(ds_merged)
            logger.debug("Merging with %s", os.path.split(f)[-1])
        
        ds_merged = ds_merged.sortby('time')
        
        # Export
        ds_merged[list(ds_merged.data_vars)[0]].encoding = encod
        
        yearset = set()
# =============================================================================
#         year_pattern = re.compile('\d{4,8}')
#         for f in filelist:
#             filename = os.path.split(os.path.splitext(f)[0])[-1]
#             var, years = sim_pattern.split(filename)
#             yearset.update(year_pattern.findall(years))
# ============================================================================= 
        yearset.update([pd.to_datetime(ds_merged.time[0].item()),
                        pd.to_datetime(ds_merged.time[-1].item())])
        
# =============================================================================
#         if not os.path.exists(os.path.join(root_folder, "merged")):
#             os.mkdir(os.path.join(root_folder, "merged"))
# =============================================================================
        
        # Delete previous files
        for f in filelist:
            os.remove(f)

        new_filepath = os.path.join(
            root_folder, 
            # "merged", 
            '_'.join([sim_var, 'SIM2', sorted(yearset)[0].strftime("%Y%m%d"), sorted(yearset)[-1].strftime("%Y%m%d")]) + '.nc'
            )
        ds_merged.to_netcdf(new_filepath)
        
        self.final_filelist[HyMoPy_var] = new_filepath
        
        self.raw_values[HyMoPy_var] = ds_merged
        
# =============================================================================
#         self.values[HyMoPy_var] = ds_merged
# =============================================================================
        
    
    #%% Merge whole folder netcdf files
    def merge_folder(self, folder, varlist=[]):    
        filelist = [f for f in os.listdir(folder) 
                    if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.nc')]
        
        # In case the function is used without a list, all variables are processed
        if len(varlist) == 0:
            varlist = set()
            # Extract all variables
            for f in filelist:
                filename = os.path.splitext(f)[0]
                sim_pattern = re.compile('.*_SIM2_')
                var = sim_pattern.findall(filename)
                if len(var) > 0:
                    var = var[0][0:-6]
                    varlist.add(var)
            
        for v in varlist:
# =============================================================================
#             HyMoPy_var = self.HyMoPy_var_by_sim_var.loc[v].item()
#             print(f"\n{'-'*(len(v)+len(HyMoPy_var)+3)}\n{v} ({HyMoPy_var})\n{'-'*(len(v)+len(HyMoPy_var)+3)}")
# =============================================================================
            
            # Extract all years
            yearlist = []
            sim_pattern = re.compile('_SIM2_')
            for f in filelist:
                filename = os.path.splitext(f)[0]
                res = sim_pattern.split(filename)
                if len(res) > 1:
                    var, years = res 
                if var == v:
                    yearlist.append(years)
                
# =============================================================================
#             print(f"   {', '.join(yearlist)}")
# =============================================================================
            
            files_to_merge = [os.path.join(folder, v + '_SIM2_' + y + '.nc') for y in yearlist]
            self.merge(files_to_merge)        
            
    
    #%% Compress
    def compress(self, filepath):    
        root_folder = os.path.split(os.path.split(filepath)[0])[0]
        
        with xr.open_dataset(filepath, decode_times = True,
                             decode_coords = 'all') as ds:
            ds.load() # to unlock the resource
            
        # Discretization compression (lossy):
        var = list(ds.data_vars)[0]
        bound_max = float(ds[var].max())
        bound_min = float(ds[var].min())
        if bound_min<0: bound_min = bound_min*1.1
        elif bound_min>0: bound_min = bound_min/1.1
        else: bound_min = bound_min - 0.01*bound_max
        scale_factor, add_offset = netcdf.compute_scale_and_offset(
            bound_min, bound_max, 16)
        ds[var].encoding['scale_factor'] = scale_factor
        ds[var].encoding['add_offset'] = add_offset
        ds[var].encoding['dtype'] = 'int16'
        ds[var].encoding['_FillValue'] = -32768
        logger.info("Applying lossy compression (scale factor %.6f, offset %.6f)", scale_factor, add_offset)
        
        # Export
        if not os.path.exists(os.path.join(root_folder, "compressed")):
            os.mkdir(os.path.join(root_folder, "compressed"))
        
        filename = os.path.splitext(os.path.split(filepath)[-1])[0]
        new_filepath = os.path.join(
            root_folder, 'compressed', filename + '_comp.nc')
        ds.to_netcdf(new_filepath)
            
        
    #%% Compress whole folder
    def compress_folder(self, folder):    
        filelist = [f for f in os.listdir(folder) 
                    if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.nc')]
        
        logger.info("Compressing %d NetCDF files", len(filelist))
        
        i = 0
        for f in filelist:
            i += 1
            logger.debug("Compressing %s (%d/%d)", f, i, len(filelist))
            
            self.compress(os.path.join(folder, f))
        
        
    #%% Clip
    def clip(self, filepath, maskpath):
        root_folder = os.path.split(filepath)[0]
        
        # Load polygon
        mask = gpd.read_file(maskpath)
        # Reproject
        src_epsg = rio.crs.CRS.from_string(self.geographic.crs_proj).to_epsg()
        mask.set_crs(epsg = src_epsg, 
                     inplace = True, allow_override = True)
        mask.to_crs(epsg = 27572, inplace = True)
        # epsg = rio.crs.CRS.from_epsg(27572)
        
# =============================================================================
#         # Expand polygon
#         # because if clipped raster is smaller than 2 pixels (on any of its
#         # dimensions), visualization softwares will have trouble to display it.
#         mask.scale(xfact = 1, yfact = 1, origin = 'center')
# =============================================================================
        
        with xr.open_dataset(filepath, decode_times = True,
                             decode_coords = 'all') as ds:
            ds.load() # to unlock the resource
        
        resolution = abs(ds.rio.transform()[0])
        
        clipped_ds = ds.rio.clip(mask.buffer(resolution).geometry.apply(mapping), 
                                 mask.crs, all_touched = True)
    
        # Export
# =============================================================================
#         if not os.path.exists(os.path.join(root_folder, "clipped")):
#             os.mkdir(os.path.join(root_folder, "clipped"))
# =============================================================================

        
        filename = os.path.splitext(os.path.split(filepath)[-1])[0]
        new_filepath = os.path.join(
            root_folder, 
            # 'clipped', 
            filename + '.nc')
        clipped_ds.to_netcdf(new_filepath)
        
    
    #%% Clip whole folder
    def clip_folder(self, folder, maskpath, varlist=[]):
        
        sim_pattern = re.compile('.*_SIM2_')
        filelist = [f for f in os.listdir(folder) 
                    if (os.path.isfile(os.path.join(folder, f))) \
                        & (os.path.splitext(f)[-1] == '.nc') \
                            & (len(sim_pattern.findall(f)) > 0)]
            
        if len(varlist) != 0:     
            sim_pattern2 = re.compile(f'{"|".join(varlist)}_SIM2_')
            filelist = [f for f in filelist
                        if (len(sim_pattern2.findall(f)) > 0)]
        
        maskname = os.path.splitext(os.path.split(maskpath)[-1])[0]
        
        logger.info("Clipping NetCDF files with mask %s", maskname)
        
        i = 0
        for f in filelist:
            i += 1
            logger.debug("Clipping %s (%d/%d)", f, i, len(filelist))
            
            self.clip(os.path.join(folder, f), maskpath)

    
#%% NOTES
"""
First implemented in May 2024, from the work of Loic Duffar (https://github.com/loicduffar),
Ronan Abhervé Nicolas Cornette and Alexandre Coche
"""
