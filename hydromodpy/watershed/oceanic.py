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
    
    def extract_data(self, out_path, geographic, oceanic_path=None):
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
        ram_path = oceanic_path+"/RAM_2020.shp"
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
        xidx, yidx = self.idx_from_global_map(oceanic_path+'/rsl_ts_26.nc',geographic)
        scenarios = ['RCP2.6','RCP4.5','RCP8.5']
        rsl_name = {'RCP2.6':'rsl_ts_26.nc',
                    'RCP4.5':'rsl_ts_45.nc',
                    'RCP8.5':'rsl_ts_85.nc'}
        self.RSL = {}
        self.RMSL = {}
        for sce in scenarios:
            nc = Dataset(oceanic_path+'/'+rsl_name[sce], "r", format="NETCDF4")
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

    def display_data(self, values):
        """
        Function to activate plots.
        
        Parameters
        ----------
        values : str
            Type of plot required : 'RMSL' or 'RSL'.
        """
        values_list = ['RMSL','RSL']
        if values not in values_list:
            logger.error('Unsupported oceanic display value: %s', values)
        if values == 'RMSL':
            oceanic_display_data(self.RMSL, self.figure_folder+'RMSL', values)
        if values == 'RSL':
            oceanic_display_data(self.RSL, self.figure_folder+'RSL', values)

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
