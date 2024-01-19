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
        self.masks:dict = {} # dict of lakes/reservoirs masks, keyed by lake_id
        self.flux_data:dict = {} # dict of lakes/reservoirs flux data dataframes, 
                                 # keyed by lake_id
        self.raster_base = geographic.watershed_dem
        self.crs_proj = geographic.crs_proj
    
    #%% ADD A NEW LAKE/RESERVOIR   
    def new_lakeres(self, mask_path:str, lake_id:int=None):
        # can be a lake or an artificial lake
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id = 0
            else:
                lake_id = np.max(self.indexes) + 1
                
        self.masks[lake_id] = toolbox.load_to_numpy(mask_path, 
                                                    base_path = self.raster_base,
                                                    dst_crs = self.crs_proj)
        
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
        
   
    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
