# -*- coding: utf-8 -*-
"""
 * Functionnality developped by Alexandre Coche (2024)
 * 
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy,
 * Alexandre Coche
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
import sys
import re
import pandas as pd
import geopandas as gpd
import numpy as np
import rasterio as rio
import matplotlib.pyplot as plt
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# HydroModPy
from tools import toolbox

#%% CLASS

class Lakeres:

    
    #%% INIT
    
    def __init__(self, geographic):
        self.n_lakeres:int = 0 # number of lakes/reservoirs
        self.indexes:list = [] # identifiers of lakes/reservoirs
        self.raster_base = geographic.watershed_dem
        self.crs_proj = geographic.crs_proj
        with rio.open(self.raster_base, 'r') as base:
            self.nodata = base.profile['nodata'] # value corresponding to the no data property 
        self.masks:dict = {} # dict of lakes/reservoirs masks, keyed by lake_id
        self.raster_array:np.ndarray = None
        raster_array = toolbox.load_to_numpy(self.raster_base,
                                              dst_crs = self.crs_proj) # np.ndarray
        self.raster_array = np.ma.array(raster_array, 
                                        mask = raster_array==self.nodata,
                                        fill_value = self.nodata,
                                        ) * 0 # masked np.ndarray with null values
        self.flux_data:dict = {} # dict of lakes/reservoirs flux data dataframes, 
                                 # keyed by lake_id
                                 
        self.data_folder = os.path.join(geographic.stable_folder,
                                   'lakeres')
        if not os.path.exists(self.data_folder):
                os.makedirs(self.data_folder)
        

    #%% ADD A NEW LAKE/RESERVOIR   
    def new_lakeres(self, mask_path:str, lake_id:int=None, src_crs=None):
        # can be a lake or an artificial lake
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id:int = 1 # initialization
            else:
                lake_id:int = np.max(self.indexes) + 1
        
        print(f"\nAdding lake n°{lake_id}")
        mask = toolbox.load_to_numpy(mask_path, 
                                     src_crs = src_crs,
                                     base_path = self.raster_base, 
                                     dst_crs = self.crs_proj)
        mask[mask == self.nodata] = 0
        # self.masks[lake_id] = mask.astype(int)
        self.masks[lake_id] = mask.astype(bool)
        
# =============================================================================
#         self.raster_array = self.raster_array + np.ma.array(self.masks[lake_id],
#                                                             fill_value = self.nodata
#                                                             ) * lake_id
# =============================================================================
        masked_newlake = np.ma.array(self.masks[lake_id],
                                     mask = self.raster_array.mask,
                                     fill_value = self.nodata
                                     )
        print('') # newline
        for idx in self.indexes:
            intersect = (self.raster_array[(self.raster_array==idx) & (masked_newlake==1)]).sum()
            if intersect > 0:
                print(f" Lake n°{lake_id} overwrites lake n°{idx} on {int(intersect)} cells.")
        self.raster_array[masked_newlake==1] = lake_id
        
# =============================================================================
#         self.raster_array = np.where(self.masks[lake_id]==1, lake_id, self.raster_array)
# =============================================================================
        
        with rio.open(self.raster_base, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = self.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'raster_array.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, self.raster_array.astype(int))
        
        
        self.flux_data[lake_id] = {}
        # Update Lakeres attributes:
        # self.idlist = self.idlist.append(lake_id)
        self.indexes = list(self.masks.keys())
        self.n_lakeres = len(self.indexes)
        
    #%% UPDATE A PREVIOUS LAKE/RESERVOIR
    def update_definition(self, lake_id:int, new_lake_id:int=None, new_mask_path:str=None):
        if new_lake_id and not new_mask_path: # just replace the key
            self.masks[new_lake_id] = self.masks.pop(lake_id)
            self.flux_data[new_lake_id] = self.flux_data.pop(lake_id)
            self.indexes = list(self.masks.keys())
            
        elif new_mask_path and not new_lake_id: # just replace the mask
            self.masks[lake_id] = toolbox.load_to_numpy(new_mask_path,
                                                        self.raster_base,
                                                        self.crs_proj)
            
        elif new_lake_id and new_mask_path: # replace both the mask and the key
            self.masks[new_lake_id] = toolbox.load_to_numpy(new_mask_path,
                                                            self.raster_base,
                                                            self.crs_proj)
            self.mask.pop(lake_id)
            self.flux_data[new_lake_id] = self.flux_data.pop(lake_id)
            self.indexes = list(self.masks.keys())
        
    #%% UPDATE ANTHROPIC FLOWS IN AND OUT OF THE LAKE/RESERVOIR
    def update_withdraw_fill(self, lake_id, withdraw_fill_ts:pd.core.series.Series):
        self.flux_data[lake_id]['WTHDRW'] = withdraw_fill_ts
        
    #%% REMOVE A LAKE/RESERVOIR
    def remove(self, lake_id):
        self.masks.pop(lake_id)
        self.flux_data.pop(lake_id)
        
        # Update Lakeres attributes:
        self.indexes = list(self.masks.keys())
        self.n_lakeres = len(self.indexes)
   
    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
