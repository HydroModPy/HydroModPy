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
import pandas as pd
import numpy as np
import os
from scipy.optimize import curve_fit
from hydromodpy.data_managers.climatic import sim2_API
from hydromodpy.watershed import sim2, initializing
from hydromodpy.geographic import Geographic
import re
from hydromodpy.tools import get_logger

logger = get_logger(__name__)

#%% CLASS

class Climatic:
    """
    Class to initialize the climate forcing data (recharge, runoff).
    """

    def __init__(self, var_list, formatting, nc_data_path, first_year, last_year, time_step='D', sim_state='transient', spatial_mean = False, geographic=None, disk_clip=None, out_path:str=None, source=None):
        """
        Parameters
        ----------
        var_list : str or list[str]
            Path of the HydroModPy outputs.
        """
        logger.info('Initializing climatic module parameters')

        self.stable_folder = initializing.stable_folder
        self.data_folder = os.path.join(self.stable_folder, 'climatic')
        self.var_list = var_list
        self.formatting = formatting
        self.nc_data_path = nc_data_path
        self.first_year = first_year
        self.last_year = last_year
        self.time_step = time_step
        self.sim_state = sim_state
        self.spatial_mean = spatial_mean
        self.geographic = geographic
        self.disk_clip = disk_clip
        self.out_path = out_path
        self.source = source #'own', 'sim2', 'era5', 'drias'
        self.box = self.geographic.xmin, self.geographic.ymin, self.geographic.xmax, self.geographic.ymax
        
        if self.source == 'sim2':
            self.sim2_API()
    #%% UPDATE FROM SIM2 REANALYSIS (online)
        
    def sim2_API(self):
        self.sim2_API = sim2_API.Sim2_API(box = self.box,
                                crs = self.geographic.crs_project, 
                                var_list=self.var_list, 
                                formatting=self.formatting, 
                                date=f"{self.first_year}-01-01/{self.last_year}-12-31")
        return 
    
    def sim2(self):
        """
        Download SIM2 reanalysis datasets and attach them to the climatic object.

        Parameters
        ----------
        var_list : str or list[str]
            Variables to download (``['recharge', 'runoff', ...]``). Accepts a
            single string which is converted to a list internally.
        nc_data_path : str
            Folder where the NetCDF files are cached (created if missing).
        first_year : int
            First year included in the extraction window.
        last_year : int, optional
            Last year to download (defaults to ``first_year`` if omitted).
        time_step : {'D', 'M'}, optional
            Temporal resolution requested when querying SIM2 (daily by default).
        sim_state : {'transient', 'steady'}, optional
            Simulation flavour; used when setting HydroModPy inputs.
        spatial_mean : bool, optional
            Average each variable over the watershed mask before storing it.
        geographic : hydromodpy.watershed.geographic.Geographic
            Geographic descriptor providing CRS, bounds, and watershed mask.
        disk_clip : str, optional
            Either ``'watershed'`` or a shapefile path controlling how cached
            NetCDF cubes are spatially clipped to save disk space.

        Returns
        -------
        None
        """
        # If a single var name is provided, convert it to a list.
        if isinstance(var_list, str): var_list = [var_list]

        # Creation of SIM2 reanalysis object:
        self.sim2_rea = sim2.Sim2(var_list=self.var_list, nc_data_path=self.nc_data_path,
                                  first_year=self.first_year, last_year=self.last_year,
                                  time_step=self.time_step, sim_state=self.sim_state,
                                  spatial_mean=self.spatial_mean, geographic=self.geographic,
                                  disk_clip=self.disk_clip)
        # Note: values are available through reanalysis.data

        for var in self.var_list:
            exec(f"self.{var} = self.sim2_rea.values[var]")
            # Get the data
            data = self.sim2_rea.values[var]
            # Construct the file path
            file_path = os.path.join(self.nc_data_path, "_"+var+".csv")
            # Save to CSV only for pandas objects (not xarray with spatial dimensions)
            # For xarray Datasets with spatial dimensions, skip CSV export to avoid memory issues
            if isinstance(data, (pd.DataFrame, pd.Series)):
                data.to_csv(file_path, index=True, sep=';')
            elif hasattr(data, 'to_dataframe'):
                if 'x' not in data.dims and 'y' not in data.dims:
                    data.to_dataframe().to_csv(file_path, index=True, sep=';')
                
    # #%% SET DATA SET TO STEADY INPUTS
    # def sim_state_method (self):
    #     """
    #     Function to update moisture based on its own values.

    #     Parameters
    #     ----------
    #     values
    #         Recharge values, float or list of float.
    #     sim_state : str
    #         Select the simulation type, steady-state or transient.
    #     """
    #     for var in var_list:
    #     self.moisture = values # recharge
    #     if isinstance(values,(dict))==False:
    #         if sim_state == 'steady':
    #             self.moisture = np.mean(self.moisture)
    #             if isinstance(self.moisture,(int,float))==False:
    #                 self.moisture = self.moisture[0]
                    
    # def update_first_clim(self, first_clim):
    #     """
    #     Define the first value of the recharge list values.

    #     Parameters
    #     ----------
    #     first_clim
    #         Choice between a float, the mean or the first value in the list of values.
    #     """
    #     self.first_clim = first_clim # 'mean', 'first' or value
#%% NOTES
