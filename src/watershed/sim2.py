# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import numpy as np
import os
import pandas as pd
import sys
from os.path import dirname, abspath
import geopandas as gpd

import rasterio as rio
import rasterio.features # necessary to avoid a bug
import xarray as xr
xr.set_options(keep_attrs = True)
import math

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from tools import toolbox

#%% CLASS

class Sim2:
    """
    Class to extract the SIM2 historic reanalysis data.
    Since 13/12/2023 these data are in open access on https://meteo.data.gouv.fr/
    (tab "Données climatologiques de référence pour le changement climatique",
     then "Données changement climatique - SIM quotidienne" : 
     https://meteo.data.gouv.fr/datasets/6569b27598256cc583c917a7 )
    """
    
    def __init__(self,
                 var_list, path_nc_data: str,
                 first_year: int, last_year: int,
                 time_step: str, sim_state: str,
                 spatial_mean=False):
        """
        Parameters
        ----------
        var_list : iterable
            List of variable names.
            HydroModPy variable names: 'recharge' | 'runoff' | 'evt' | 'precip' | 'temp'
            Also works with SIM2 variable names: 'DRAINC_Q' | 'RUNC_Q' | 'EVAP_Q' | 'PRELIQ_Q' | 'T_Q' ...
        path_nc_data : str (optional)
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
            ...
        sim_state : str
            'transient' | 'steady'
            If 'steady', the time mean will be used.
        spatial_mean : bool
            False (default). If True, data will be spatially averaged and returned
            as a pandas.DataFrame instead of an xarray.DataSet.

        Returns
        -------
        None. Create or update the netcdf files.

        """
        
        self.var_list = var_list
        self.path_nc_data = path_nc_data
        self.first_date = pd.to_datetime(f"{first_year}-01-01", format = "%Y-%m-%d")
        if last_year is None:
            self.last_date = pd.to_datetime('today').normalize()
        else:
            self.last_date = pd.to_datetime(f"{last_year}-12-31", format = "%Y-%m-%d")
        self.time_step = time_step
        self.sim_state = sim_state
        self.spatial_mean = spatial_mean
        
# =============================================================================
#         # Data already available for each variable 
#         nc_file_by_var = {} 
#         
#         if self.path_nc_data is not None:
#             if len(os.listdir(self.path_nc_data)) > 0: # folder is not empty
#                 for var in self.var_list:
#                     if 0:
#                         nc_file_by_var = 0
#                     else:
#                         nc_file_by_var = None
#             else:
#                 for var in self.var_list:
#                     nc_file_by_var = None
# =============================================================================
                    
        
    
    #%% ...
    
    def ...
        
        
#%% NOTES
"""
First implemented in May 2024, from the work of Loic Duffar (https://github.com/loicduffar),
Ronan Abhervé Nicolas Cornette and Alexandre Coche
"""
