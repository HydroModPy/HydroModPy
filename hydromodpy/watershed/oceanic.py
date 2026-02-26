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
import os
import numpy as np
import pandas as pd
import geopandas as gpd
from netCDF4 import Dataset
import sys
import matplotlib.pyplot as plt
from hydromodpy.tools import get_logger

# Root
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from hydromodpy.tools import toolbox
import requests
from datetime import datetime, timedelta

logger = get_logger(__name__)

#%% CLASS

class Oceanic:
    """
    Add oceanic data from specific data at France scale.
    Allow to define head boundary with water levels in groundwater flow model.
    """
    
    def __init__(self):
        """
        Parameters
        ----------
        MSL : float
            The default is None.
        """
        self.MSL = None
        self.oceanic_path = None

#%% FUNCTIONS
        
    def update_MSL(self, value):
        """
        Update the MSL value.
        
        Parameters
        ----------
        value : float
            Elevation Meter Above Sea Level [m]. The default is None.
        """
        self.MSL = value
    
    def extract_local_data(self, out_path, geographic, oceanic_path=None):
        """
        Clip data at the model_domain (watershed) scale.
        
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs.
        geographic : object
            Variable object of the model domain (watershed).
        oceanic_path : str, optional
            Path of the folder with the oceanic data. The default is None.
        """
        self.figure_folder = os.path.join(out_path,'results_stable/_figures/oceanic/')
        if not os.path.exists(self.figure_folder):
            os.makedirs(self.figure_folder)
        ram_path = self.mean_sea_level(geographic, oceanic_path)
        if ram_path != None:
            self.rise_sea_level(geographic, oceanic_path)

    def mean_sea_level(self, geographic, oceanic_path):
        """
        Extract historical mean sea level in tide sea level stations.

        Returns
        -------
        ram_path : str
            Path of the tide sea level stations data in a shapefile.
        """
        ram_path = os.path.join(oceanic_path, "RAM_2020.shp")
        if not os.path.exists(ram_path):
            ram_path = None
            return ram_path
        gdf = gpd.read_file(ram_path)
        ports = gdf.to_crs(epsg=2154)
        ports = ports.dropna(subset=['NM', 'ZH_Ref'])
        ports = ports.reset_index()
        dist = np.sqrt((geographic.centroid[0]-ports.geometry.x.values)**2+(geographic.centroid[1]-ports.geometry.y.values)**2)
        index = (np.abs(dist)).argmin()
        self.port = ports.SITE[index]
        self.MSL = ports.NM[index]/100+ports.ZH_Ref[index]
        return ram_path

    def rise_sea_level(self, geographic, oceanic_path):
        """
        Extract future sea level projections under different greenhouse gas emission scenarios.
        """
        xidx, yidx = self.idx_from_global_map(os.path.join(oceanic_path, 'rsl_ts_26.nc'),geographic)
        scenarios = ['RCP2.6'] #,'RCP4.5','RCP8.5']
        rsl_name = {'RCP2.6':'rsl_ts_26.nc',
                    'RCP4.5':'rsl_ts_45.nc',
                    'RCP8.5':'rsl_ts_85.nc'}
        self.RSL = {}
        self.RMSL = {}
        for sce in scenarios:
            nc = Dataset(os.path.join(oceanic_path, rsl_name[sce]), "r", format="NETCDF4")
            date = np.array(nc.variables['time'][:])
            df = pd.DataFrame(date, columns=["date"])
            df.index = pd.to_datetime(df['date'],format='%Y')
            df = df.drop(['date'], axis=1)
            v = []; vh = []; vl = []; vstdh = []; vstdl = []
            for i in range(0, len(nc.variables['time'][:])):
                med = nc.variables['slr_md'][i][yidx][xidx]
                v.append(med)
                high = nc.variables['slr_he'][i][yidx][xidx]
                vh.append(med+(1.645*high))
                vstdh.append(med+high)
                low = nc.variables['slr_le'][i][yidx][xidx]
                vstdl.append(med-low)
                vl.append(med-(1.645*low))

            df['median'] = v
            df['std high'] = vstdh
            df['std low'] = vstdl
            df['95th per'] = vh
            df['5th per'] = vl

            df1 = df.copy()
            df1 = df1 - df1['median'].loc['2020'].values[0] + self.MSL

            df = df.resample('D')
            df = df.interpolate(method='linear')
            df1 = df1.resample('D')
            df1 = df1.interpolate(method='linear')
            self.RSL[sce] = df
            self.RMSL[sce] = df1

    def idx_from_global_map(self, path, geographic):
        """
        Index and project zones of interest.

        Parameters
        ----------
        path : str
            Path of the specific NetCDF file.
        geographic : TYPE
            DESCRIPTION.

        Returns
        -------
        xidx : int
            Index x.
        yidx : int
            Index y.
        """
        nc = Dataset(path, "r", format="NETCDF4")
        find_idx = np.zeros((np.shape(nc.variables['slr_md'][0])[0]*np.shape(nc.variables['slr_md'][0])[1],5))
        compt = 0
        for x in range(0,np.shape(nc.variables['slr_md'][0])[1]):
            for y in range(0,np.shape(nc.variables['slr_md'][0])[0]):
                find_idx[compt,:] = [x,y,nc.variables['x'][x].data.item(),nc.variables['y'][y].data.item(),nc.variables['slr_md'][0][y][x]]
                compt +=1
        find_idx = find_idx[~np.isnan(find_idx).any(axis=1)]
        distance = np.sqrt((find_idx[:,3]-geographic.centroid_long_lat_Greenwich[0])**2+(find_idx[:,2]-geographic.centroid_long_lat_Greenwich[1])**2)
        idx = distance.argmin()
        xidx = find_idx[idx][0]
        yidx = find_idx[idx][1]
        return int(xidx), int(yidx)

    def download_SHOM_data(self, geographic, start_date, end_date, write=True):
        """
        Download sea-level data from SHOM (Service Hydrographique et Océanographique de la Marine) website
        Based on catchment centroid coordinates, the closest tide gauge station is identified and its data is downloaded.

            Parameters
        ----------
        geographic : object
            Variable object of the model domain (watershed).
        start_date : str
            Start date of the data to be downloaded (format: 'YYYY-MM-DD').
        end_date : str
            End date of the data to be downloaded (format: 'YYYY-MM-DD').
        """
        # Get the list of tide gauge stations from SHOM website
        url = 'https://services.data.shom.fr/maregraphie/service/tidegauges'
        tide_gauge_list = requests.get(url)
        tide_gauge_list = tide_gauge_list.json()
        self.tide_gauge_df = pd.DataFrame(tide_gauge_list)

        # Identify the closest tide gauge station to the catchment centroid
        self.tide_gauge_df['catchment_dist'] = np.sqrt((self.tide_gauge_df['longitude'] - geographic.centroid_long_lat[1])**2 + (self.tide_gauge_df['latitude'] - geographic.centroid_long_lat[0])**2)
        self.closest_tg = self.tide_gauge_df.loc[self.tide_gauge_df['catchment_dist'].idxmin()]
        closest_tg_id = self.closest_tg['shom_id']
        tg_id = str(closest_tg_id)

        # Check if data is already downloaded
        output_folder = os.path.join(geographic.stable_folder, 'oceanic')
        output_filename = f'sea-level-shom_{tg_id}_{start_date}_{end_date}.csv'
        if os.path.exists(os.path.join(output_folder, output_filename)):
            print(f"Data for tide gauge station {self.closest_tg['name']} already downloaded. Loading from file.")
            self.SHOM_data = pd.read_csv(os.path.join(output_folder, output_filename), parse_dates=['timestamp'])
            
        else:
            
            # Get the vertical reference of the closest tide gauge station
            print(f"Closest tide gauge station: {self.closest_tg['name']} at ({self.closest_tg['latitude']}, {self.closest_tg['longitude']})")
            url = f'https://services.data.shom.fr/maregraphie/service/completetidegauge/{closest_tg_id}'
            tide_gauge_info = requests.get(url)
            tide_gauge_info = tide_gauge_info.json()
            zh_ref = float(tide_gauge_info['verticalRef']['zh_ref']) # Vertical reference of the tide gauge station

            # Download sea-level data for the closest tide gauge station
            # iterates over 31-day periods to avoid data download issues for long time series
            sources = '3' # code to get validated data
            interval = '60' # data interval in minutes
            start_date_temp = datetime.strptime(start_date, '%Y-%m-%d')
            end_date_temp = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=31)
            i=0
            while end_date_temp < datetime.strptime(end_date, '%Y-%m-%d') or i==0:
                if i!=0:
                    start_date_temp = end_date_temp + timedelta(days=1)
                    end_date_temp = start_date_temp + timedelta(days=31)
                dtStart = f'{start_date_temp.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
                dtEnd = f'{end_date_temp.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
                url = f'https://services.data.shom.fr/maregraphie/observation/json/{tg_id}?sources={sources}&dtStart={dtStart}&dtEnd={dtEnd}&interval={interval}'
                tg_data = requests.get(url)
                tg_data = tg_data.json()
                if i==0:
                    tg_df = pd.DataFrame(tg_data['data'])[['timestamp', 'value']]
                else:
                    tg_df = pd.concat([tg_df, pd.DataFrame(tg_data['data'])[['timestamp', 'value']]], ignore_index=True)
                i+=1
                
            # Process the downloaded data
            tg_df['value'] = pd.to_numeric(tg_df['value'], errors='coerce')
            tg_df['value'] = tg_df['value'] + zh_ref # Convert vertical level from hydrographic to IGN reference
            tg_df['timestamp'] = pd.to_datetime(tg_df['timestamp'])
            tg_df = tg_df[tg_df['timestamp'] <= datetime.strptime(end_date, '%Y-%m-%d')] # Keep only data until the specified end date
            self.SHOM_data = tg_df

            # Optionally, write the data to a CSV file
            if write:
                output_path = os.path.join(output_folder, output_filename)
                if not os.path.exists(os.path.dirname(output_path)):
                    os.makedirs(os.path.dirname(output_path))
                tg_df.to_csv(output_path, index=False)

    def display_data(self, values):
        """
        Function to activate plots.
        
        Parameters
        ----------
        values : str
            Type of plot required : 'RMSL' or 'RSL'.
        """
        values_list = ['RMSL','RSL']
        if values == 'RMSL':
            oceanic_display_data(self.RMSL, self.figure_folder+'RMSL', values)
        elif values == 'RSL':
            oceanic_display_data(self.RSL, self.figure_folder+'RSL', values)
        else:
            logger.error('Unsupported oceanic display value: %s', values)

#%% DISPLAY

def oceanic_display_data(data, figure_folder, value):
    """
    Plot functions.

    Parameters
    ----------
    data : TYPE
        DataFrame with data to plot.
    figure_folder : str
        Folder path to save figures.
    value : str
        Type of plot required : 'RMSL' or 'RSL'.
    """
    color_dict = {'RCP2.6':'dodgerblue',
                  'RCP8.5':'red',
                  'RCP4.5':'salmon'}
    
    fontprop = toolbox.plot_params(15,15,18,20)
    fig = plt.figure()
    
    for sce in data:
        d = data[sce].index.values
        data[sce]['median'].plot(c=color_dict[sce], label=sce+': median values')
        plt.fill_between(d , data[sce]['std high'], data[sce]['std low'],facecolor=color_dict[sce], alpha=0.2, label=sce +': 5th and 95th perc')
        #data[sce]['5th per'].plot(c=color_dict[sce],ls='--', label=sce)
        #data[sce]['95th per'].plot(c=color_dict[sce],ls='--', label=sce)

    plt.legend(loc='best')
    plt.xlabel('Date')
    if value =='RMSL':
        plt.ylabel('Mean Sea Level [m]')
    if value =='RSL':
        plt.ylabel('Rise Sea Level [m]')
    
    plt.tight_layout()
    name_out = figure_folder + 'plot'
    fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')

#%% NOTES
