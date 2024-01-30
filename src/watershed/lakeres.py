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
    
    def __init__(self, stable_folder):
                                 
        self.data_folder = os.path.join(stable_folder, 'lakeres')
        if not os.path.exists(self.data_folder):
                os.makedirs(self.data_folder)
                
        self.n_lakeres:int = 0, # number of lakes/reservoirs
        self.indexes:list = [], # identifiers of lakes/reservoirs
        self.maskmx_paths:dict = {}, # dict of lakes/reservoirs masks paths, 
                                   # keyed by lake_id
                                   # masks correspond to te maximal extent of 
                                   # the lake, or larger (see computation of 
                                   # bathymetry)   
        self.ssmx:dict = {}, # dict of maximum stages keyed by lake_id
        self.bdlknc:dict = {}, # dict of lakebed leakance
        # dict of lakes/reservoirs flux data dataframes, keyed by lake_id:
        self.prcplk:dict = {},
        self.evaplk:dict = {},
        self.rnf:dict = {},
        self.wthdrw:dict = {},
        

    #%% ADD A NEW LAKE/RESERVOIR   
    def new_lakeres(self, maskmx_path:str, lake_id:int=None, src_crs=None,
                    geographic = None):
        # NB: can be a lake or an artificial lake
        
        # Store/infer lake_id
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id:int = 1 # initialization
            else:
                lake_id:int = np.max(self.indexes) + 1
        print(f"\nAdding lake n°{lake_id}")
        
        # Lake/reservoir mask
        self.maskmx_paths = maskmx_path
        
        # Check overlapping between lakes   
        if geographic:     
            with rio.open(geographic.watershed_dem, 'r') as base:
                nodata = base.profile['nodata'] # value corresponding to the no data property 

            maskmx = toolbox.load_to_numpy(maskmx_path, 
                                         src_crs = src_crs,
                                         base_path = geographic.watershed_dem, 
                                         dst_crs = geographic.crs_proj)
            
            maskmx[maskmx == nodata] = 0
            
            for idx in self.indexes:
                prev_maskmx = toolbox.load_to_numpy(maskmx_path, 
                                                    src_crs = src_crs,
                                                    base_path = geographic.watershed_dem, 
                                                    dst_crs = geographic.crs_proj)
                
                intersect = (maskmx*prev_maskmx).sum()
                if intersect > 0:
                    print(f"\n NB: Lake n°{lake_id} overwrites lake n°{idx} on {int(intersect)} cells.")
        
        # Default values for required parameters
# =============================================================================
#         self.ssmx[lake_id] = # maximum de la topo
# =============================================================================
        self.bdlknc[lake_id] = 86400 # default = 1 m/s
        
# =============================================================================
#         self.flux_data[lake_id] = pd.DataFrame(
#             data = np.array([[0], [0], [0], [0]]).transpose(), 
#             columns = ['PRCPLK', 'EVAPLK', 'RNF', 'WTHDRW'], 
#             index = [0])
# =============================================================================
        self.prcplk[lake_id] = 0
        self.evaplk[lake_id] = 0
        self.rnf[lake_id] = 0
        self.wthdrw[lake_id] = 0
        
        
        # Update Lakeres attributes:
        # self.idlist = self.idlist.append(lake_id)
        self.indexes = list(self.masks.keys())
        self.n_lakeres = len(self.indexes)
        
        
    #%% UPDATE A PREVIOUS LAKE/RESERVOIR
    def update_definition(self, lake_id:int, new_lake_id:int=None, new_maskmx_path:str=None):
        if new_lake_id and not new_maskmx_path: # just replace the key
            self.maskmx_paths[new_lake_id] = self.maskmx_paths.pop(lake_id)
            self.prcplk[new_lake_id] = self.prcplk.pop(lake_id)
            self.evaplk[new_lake_id] = self.evaplk.pop(lake_id)
            self.rnf[new_lake_id] = self.rnf.pop(lake_id)
            self.wthdrw[new_lake_id] = self.wthdrw.pop(lake_id)
            self.indexes = list(self.masks.keys())
            
        elif new_maskmx_path and not new_lake_id: # just replace the mask
            self.maskmx_paths[lake_id] = new_maskmx_path
            
        elif new_lake_id and new_maskmx_path: # replace both the mask and the key
            self.maskmx_paths[new_lake_id] = new_maskmx_path
            self.maskmx_paths.pop(lake_id)
            self.prcplk[new_lake_id] = self.prcplk.pop(lake_id)
            self.evaplk[new_lake_id] = self.evaplk.pop(lake_id)
            self.rnf[new_lake_id] = self.rnf.pop(lake_id)
            self.wthdrw[new_lake_id] = self.wthdrw.pop(lake_id)
            self.indexes = list(self.masks.keys())
        
        
        
    #%% UPDATE MAXIMUM STAGES (= WATER LEVELS)
    def update_stagemax(self, lake_id, ssmx):
        self.ssmx[lake_id] = ssmx
        
        
    #%% UPDATE FLOWS IN AND OUT OF THE LAKE/RESERVOIR    
    def update_precip(self, lake_id, src):
        self.prcplk[lake_id] = src
        
    def update_evap(self, lake_id, src):
        self.evaplk[lake_id] = src
        
    def update_runoff(self, lake_id, src):
        self.rnf[lake_id] = src
        
    def update_withdraw_fill(self, lake_id, src):
        self.wthdrw[lake_id] = src
        
        
    #%% REMOVE A LAKE/RESERVOIR
    def remove(self, lake_id):
        self.masks.pop(lake_id)
        self.prcplk.pop(lake_id)
        self.evaplk.pop(lake_id)
        self.rnf.pop(lake_id)
        self.wthdrw.pop(lake_id)
        
        # Update Lakeres attributes:
        self.indexes = list(self.masks.keys())
        self.n_lakeres = len(self.indexes)
   
    
   #%% FORMAT ALL ATTRIBUTES INTO INPUTS FOR MODFLOW
    def format_to_modflow(self, geographic, climatic):
        #%%% Format lakarr:
        # -----------------
        # Load masked np.array of watershed and initialize lakarr
        with rio.open(geographic.watershed_dem, 'r') as base:
            nodata = base.profile['nodata'] # value corresponding to the no data property 
        watershed_mask = toolbox.load_to_numpy(geographic.watershed_dem,
                                               dst_crs = geographic.crs_proj) 
        lakarr = np.ma.array(watershed_mask, 
                            mask = watershed_mask==nodata,
                            fill_value = nodata,
                            ) * 0 # masked np.ndarray with null values
        
        # Format lakes maskmx (maximal extents)
        for lake_id in self.indexes:
            maskmx = toolbox.load_to_numpy(self.maskmx_paths[lake_id], 
                                           src_crs = None,
                                           base_path = geographic.watershed_dem, 
                                           dst_crs = geographic.crs_proj)
        
            maskmx[maskmx == nodata] = 0
            maskmx = maskmx.astype(bool)
        
# =============================================================================
#             lakarr = lakarr + np.ma.array(maskmx,
#                                           fill_value = nodata
#                                           ) * lake_id
# =============================================================================
            maskmx = np.ma.array(maskmx,
                                 mask = watershed_mask==nodata,
                                 fill_value = nodata
                                 )
    
            lakarr[maskmx==1] = lake_id
        
# =============================================================================
#             lakarr = np.where(maskmx==1, lake_id, lakarr)
# =============================================================================
        
        # Check overlapping between lakes   
        if geographic:     
            with rio.open(geographic.watershed_dem, 'r') as base:
                nodata = base.profile['nodata'] # value corresponding to the no data property 

            maskmx = toolbox.load_to_numpy(maskmx_path, 
                                         src_crs = src_crs,
                                         base_path = geographic.watershed_dem, 
                                         dst_crs = geographic.crs_proj)
            
            maskmx[maskmx == nodata] = 0
            
            for idx in self.indexes:
                prev_maskmx = toolbox.load_to_numpy(maskmx_path, 
                                                    src_crs = src_crs,
                                                    base_path = geographic.watershed_dem, 
                                                    dst_crs = geographic.crs_proj)
                
                intersect = (maskmx*prev_maskmx).sum()
                if intersect > 0:
                    print(f"\n NB: Lake n°{lake_id} may overwrite lake n°{idx} on {int(intersect)} cells.")
        

        # Export
        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'lakarr.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, self.raster.astype(int))
            
        
        #%%% Format fluxes data
        # ---------------------
        if isinstance(src, pd.core.series.Series):
            0
       
        # return stages, lakarr, bdlknc, flux_data
       
   
    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
