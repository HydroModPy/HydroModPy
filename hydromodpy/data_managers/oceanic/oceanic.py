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
            # Why/how this block is written:
            # - Use a context manager so each NetCDF file is always closed immediately.
            # - Slice all time steps at once ([:, yidx, xidx]) instead of iterating in
            #   Python, which is faster and keeps the same formulas as the original loop.
            with Dataset(os.path.join(oceanic_path, rsl_name[sce]), "r", format="NETCDF4") as nc:
                date = np.asarray(nc.variables['time'][:])
                med = np.ma.filled(nc.variables['slr_md'][:, yidx, xidx], np.nan).astype(float, copy=False)
                high = np.ma.filled(nc.variables['slr_he'][:, yidx, xidx], np.nan).astype(float, copy=False)
                low = np.ma.filled(nc.variables['slr_le'][:, yidx, xidx], np.nan).astype(float, copy=False)

            df = pd.DataFrame(index=pd.to_datetime(date, format='%Y'))
            df['median'] = med
            df['std high'] = med + high
            df['std low'] = med - low
            df['95th per'] = med + (1.645 * high)
            df['5th per'] = med - (1.645 * low)

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
        # Vectorized nearest-cell lookup:
        # - build a full distance field once with NumPy broadcasting,
        # - mask invalid cells (NaN in slr_md/x/y),
        # - pick the minimum distance index.
        # This preserves the original behavior while avoiding nested Python loops.
        with Dataset(path, "r", format="NETCDF4") as nc:
            slr = np.ma.filled(nc.variables['slr_md'][0], np.nan).astype(float, copy=False)
            x_vals = np.asarray(nc.variables['x'][:], dtype=float)
            y_vals = np.asarray(nc.variables['y'][:], dtype=float)

        valid = np.isfinite(slr)
        valid &= np.isfinite(y_vals)[:, None]
        valid &= np.isfinite(x_vals)[None, :]
        if not np.any(valid):
            raise ValueError(f"No valid slr_md cell found in NetCDF file: {path}")

        dy = y_vals[:, None] - geographic.centroid_long_lat_Greenwich[0]
        dx = x_vals[None, :] - geographic.centroid_long_lat_Greenwich[1]
        distance2 = (dy * dy) + (dx * dx)
        distance2[~valid] = np.inf

        idx = int(np.argmin(distance2))
        yidx, xidx = np.unravel_index(idx, distance2.shape)
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
        session = requests.Session()
        url = 'https://services.data.shom.fr/maregraphie/service/tidegauges'
        tide_gauge_list = session.get(url)
        tide_gauge_list = tide_gauge_list.json()
        self.tide_gauge_df = pd.DataFrame(tide_gauge_list)

        # Identify the closest tide gauge station to the catchment centroid
        self.tide_gauge_df['catchment_dist'] = np.sqrt((self.tide_gauge_df['longitude'] - geographic.centroid_long_lat[1])**2 + (self.tide_gauge_df['latitude'] - geographic.centroid_long_lat[0])**2)
        self.closest_tg = self.tide_gauge_df.loc[self.tide_gauge_df['catchment_dist'].idxmin()]
        closest_tg_id = self.closest_tg['shom_id']
        tg_id = str(closest_tg_id)

        # Check if data is already downloaded
        output_folder = os.path.join(geographic.stable_folder, 'oceanic')
        startdate = start_date.replace('-', '')
        enddate = end_date.replace('-', '')
        output_filename = f'sealevel_shom_{tg_id}_{startdate}_{enddate}_H.csv' # TYPE_PRODUCT_ID_startdate_enddate_freq.ext
        if os.path.exists(os.path.join(output_folder, output_filename)):
            print(f"Data for tide gauge station {self.closest_tg['name']} already downloaded. Loading from file.")
            self.SHOM_data = pd.read_csv(os.path.join(output_folder, output_filename), parse_dates=['timestamp'])
            
        else:
            # Get the vertical reference of the closest tide gauge station
            print(f"Closest tide gauge station: {self.closest_tg['name']} at ({self.closest_tg['latitude']}, {self.closest_tg['longitude']})")
            url = f'https://services.data.shom.fr/maregraphie/service/completetidegauge/{closest_tg_id}'
            tide_gauge_info = session.get(url)
            tide_gauge_info = tide_gauge_info.json()
            zh_ref = float(tide_gauge_info['verticalRef']['zh_ref']) # Vertical reference of the tide gauge station

            # Download sea-level data for the closest tide gauge station
            # iterates over 31-day periods to avoid data download issues for long time series
            # Why/how this loop is structured:
            # - SHOM requests are split into fixed 31-day chunks to keep API calls reliable.
            # - We advance one contiguous window at a time until end_limit, with no
            #   special-case "first iteration" branch, which keeps the logic simpler
            #   and avoids off-by-one/date-gap issues between chunks.
            sources = '3' # code to get hourly validated data
            interval = '60' # data interval in minutes
            end_limit = datetime.strptime(end_date, '%Y-%m-%d')
            start_date_temp = datetime.strptime(start_date, '%Y-%m-%d')
            chunks = []
            # Keep the original chunked loop logic, but optimize the hot path:
            # - Bound each request window to `end_limit` to avoid over-fetching and post-filter waste.
            # - Append per-window frames to `chunks` and concatenate once after the loop, which is
            #   much faster than repeated `pd.concat` inside the loop.
            # - Reuse the same HTTP session (`session.get`) to reduce connection overhead.
            while start_date_temp <= end_limit:
                end_date_temp = min(start_date_temp + timedelta(days=31), end_limit)
                dtStart = f'{start_date_temp.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
                dtEnd = f'{end_date_temp.strftime("%Y-%m-%d")}T00%3A00%3A00Z'
                url = f'https://services.data.shom.fr/maregraphie/observation/json/{tg_id}?sources={sources}&dtStart={dtStart}&dtEnd={dtEnd}&interval={interval}'
                tg_data = session.get(url).json()
                chunk_df = pd.DataFrame(tg_data.get('data', []))
                if not chunk_df.empty:
                    chunk_df = chunk_df.reindex(columns=['timestamp', 'value'])
                    chunks.append(chunk_df[['timestamp', 'value']])
                start_date_temp = end_date_temp + timedelta(days=1)
            tg_df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=['timestamp', 'value'])
                 
            # Process the downloaded data
            tg_df['value'] = pd.to_numeric(tg_df['value'], errors='coerce')
            tg_df['value'] = tg_df['value'] + zh_ref # Convert vertical level from hydrographic to IGN reference
            tg_df['timestamp'] = pd.to_datetime(tg_df['timestamp'])
            tg_df = tg_df[tg_df['timestamp'] <= end_limit] # Keep only data until the specified end date
            self.SHOM_data = tg_df

            # Optionally, write the data to a CSV file
            if write:
                output_path = os.path.join(output_folder, output_filename)
                if not os.path.exists(os.path.dirname(output_path)):
                    os.makedirs(os.path.dirname(output_path))
                tg_df.to_csv(output_path, index=False)
        session.close()

    def load_local_shom_data(self, csv_path):
        """
        Load pre-downloaded SHOM data from a local CSV file.

        Parameters
        ----------
        csv_path : str
            Path to a CSV file with at least ``timestamp`` and ``value`` columns.
        """
        if csv_path is None:
            raise ValueError("Local SHOM CSV path is missing")

        csv_path = os.path.abspath(str(csv_path))
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Local SHOM CSV not found: {csv_path}")

        df = pd.read_csv(csv_path, parse_dates=['timestamp'])
        required_columns = {'timestamp', 'value'}
        missing = required_columns.difference(df.columns)
        if missing:
            raise ValueError(
                f"Local SHOM CSV missing required columns: {sorted(missing)}"
            )

        df = df[['timestamp', 'value']].copy()
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna(subset=['timestamp', 'value']).reset_index(drop=True)
        if df.empty:
            raise ValueError(f"Local SHOM CSV has no valid rows: {csv_path}")

        self.SHOM_data = df

    def fetch_msl_or_default(
        self,
        geographic,
        start_date: str = "2003-01-01",
        end_date: str = "2003-01-30",
        default: float = 0.0,
        source: str = "web",
        local_csv_path: str | None = None,
    ) -> float:
        """Fetch MSL and return its mean, or ``default`` on failure.

        Parameters
        ----------
        geographic : object
            Watershed geographic object used to locate the nearest tide gauge.
        start_date, end_date : str
            Date range for the SHOM download (format ``'YYYY-MM-DD'``).
        default : float
            Value returned when the download fails (network unavailable, …).
        source : str
            Source mode for MSL retrieval:
            - ``"web"``: download from SHOM API
            - ``"local"``: read from ``local_csv_path``
            - ``"auto"``: local first, then web fallback
        local_csv_path : str | None
            Local SHOM CSV used in ``"local"``/``"auto"`` mode.

        Returns
        -------
        float
            Mean sea level in metres.
        """
        source_mode = str(source).strip().lower()
        if source_mode not in {"web", "local", "auto"}:
            print(f"Unsupported MSL source '{source}', using 'auto'")
            source_mode = "auto"

        if source_mode in {"local", "auto"}:
            if local_csv_path is None:
                if source_mode == "local":
                    print("Local MSL source selected but no CSV path provided, "
                          f"using default MSL={default}")
                    return default
            else:
                try:
                    self.load_local_shom_data(local_csv_path)
                    return float(self.SHOM_data["value"].mean())
                except Exception as exc:
                    if source_mode == "local":
                        print(f"Local SHOM load failed ({exc}), using default MSL={default}")
                        return default
                    print(f"Local SHOM load failed ({exc}), trying SHOM web download.")

        if source_mode in {"web", "auto"}:
            try:
                self.download_SHOM_data(geographic, start_date=start_date, end_date=end_date)
                return float(self.SHOM_data["value"].mean())
            except Exception as exc:
                print(f"SHOM download failed ({exc}), using default MSL={default}")
                return default

        return default

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
