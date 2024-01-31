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
        """
        Class to initialize the lake/reservoir option.
        At this point, no lake/reservoir is defined. The process of defining
        a lake/reservoir is done during at a later stage using new_lakeres.
        Note that if the class lakeres is activated, but no lake/reservoir has
        been defined when running the modflow model, then the option 
        lake/reservoir will be automatically deactivated.

        Parameters
        ----------
        stable_folder : str
            Path where to store stable results for the current simulation

        """
                                 
        self.data_folder = os.path.join(stable_folder, 'lakeres')
        if not os.path.exists(self.data_folder):
                os.makedirs(self.data_folder)
                
        self.n_lakeres:int = 0 # number of lakes/reservoirs
        self.indexes:list = [] # identifiers of lakes/reservoirs
        self.maskmx_file_by_lake:dict = {} # dict of lakes/reservoirs masks paths, 
                                   # keyed by lake_id
                                   # masks correspond to te maximal extent of 
                                   # the lake, or larger (see computation of 
                                   # bathymetry)   
        self.mask_crs_by_lake:dict = {} # user has the possibility to define the source
                                         # CRS of the mask file (if not embeded in the file)
        self.bathymetry_by_lake:dict = {} # bathymetry raster paths, 
                                           # or computation option such as 'cuboid' 
                                           # or nothing (topography will be used as bathymetry)
        self.bathy_crs_by_lake:dict = {}
        self.ssmx_by_lake:dict = {} # dict of maximum stages keyed by lake_id
        self.volmx_by_lake:dict = {}
        self.bdlknc_by_lake:dict = {} # dict of lakebed leakance
        # dict of lakes/reservoirs flux data dataframes, keyed by lake_id:
        self.prcplk_by_lake:dict = {}
        self.evaplk_by_lake:dict = {}
        self.rnf_by_lake:dict = {}
        self.wthdrw_by_lake:dict = {}
        

    #%% ADD A NEW LAKE/RESERVOIR   
    def new_lakeres(self, maskmx_file:str, lake_id:int=None, mask_crs=None,
                    bathymetry_raster:str=None, bathy_crs=None, 
                    ssmx:float=None, volmx:float=None, bdlknc:float=86400, # default = 1 m/s
                    prcplk=0, evaplk=0, rnf=0, wthdrw=0,
                    ):
        """
        Note that lakeres can be a lake or a reservoir.
        
        Parameters
        ----------
        maskmx_file : str
            Path to the mask file (shapefile or raster).
            Works with NetCDF files?
        lake_id : int, optional
            DESCRIPTION. The default is None.
        mask_crs : TYPE, optional
            DESCRIPTION. The default is None.
        bathymetry_raster : str, optional
            DESCRIPTION. The default is None.
        bathy_crs : TYPE, optional
            DESCRIPTION. The default is None.
        ssmx : float, optional
            DESCRIPTION. The default is None.
        volmx : float, optional
            DESCRIPTION. The default is None.
        bdlknc : float, optional
            DESCRIPTION. The default is 86400 m/d (= 1 m/s)
        prcplk : float|array|file_path(str), optional
            Input for precipitations on the lake/reservoir. The default is 0 m/d 
            As for the next 3 parameters, prcplk can be defined by a
                - float: same value for all periods
                - pd.DataFrame: with times as index. Choosen times should also
                be present in watershed.climatic.recharge
                - file path: a .csv array or a .tif map or a .nc space-time array
        evaplk : float|array|file_path(str)|mode(str), optional
            Input for evaporation from the lake/reservoir. The default is 0 m/d
            As for the next parameter, evaplk can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic.recharge < 0.
        rnf : float|array|file_path(str)|mode(str), optional
            Input for runoff to the lake/reservoir. The default is 0 m/d
            As for the previous parameter, rnf can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic.runoff.
        wthdrw : float|array|file_path(str), optional
            Input for anthropic fluxes on the lake (withdrawal and filling). 
            The default is 0 m/d
            wthdrw integrates the sum of water removal (positive values) and
            water addition (negative values).

        Returns
        -------
        None.

        """
        
        # Store/infer lake_id
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id:int = 1 # initialization
            else:
                lake_id:int = np.max(self.indexes) + 1
        print(f"\nAdding lake n°{lake_id}")
        
        # Lake/reservoir geometry
        self.maskmx_file_by_lake[lake_id] = maskmx_file
        self.mask_crs_by_lake[lake_id] = mask_crs
        self.bathymetry_by_lake[lake_id] = bathymetry_raster
        self.bathy_crs_by_lake[lake_id] = bathy_crs
        self.ssmx_by_lake[lake_id] = ssmx
        self.volmx_by_lake[lake_id] = volmx

        # Lake/reservoir parameters
        self.bdlknc_by_lake[lake_id] = bdlknc # default = 1 m/s
        
        # Lake/reservoir inflows and outflows
        self.prcplk_by_lake[lake_id] = prcplk
        self.evaplk_by_lake[lake_id] = evaplk
        self.rnf_by_lake[lake_id] = rnf
        self.wthdrw_by_lake[lake_id] = wthdrw

        # Update Lakeres attributes:
        # self.idlist = self.idlist.append(lake_id)
        self.indexes = list(self.maskmx_file_by_lake.keys())
        self.n_lakeres = len(self.indexes)
        
        
    #%% UPDATE A PREVIOUS LAKE/RESERVOIR
    def update_definition(self, lake_id:int, new_lake_id:int=None, new_maskmx_path:str=None):
        attr_list = [self.maskmx_file_by_lake, self.mask_crs_by_lake, 
                     self.bathymetry_by_lake, self.bathy_crs_by_lake,
                     self.ssmx_by_lake, self.volmx_by_lake, self.prcplk_by_lake, 
                     self.evaplk_by_lake, self.rnf_by_lake, self.wthdrw_by_lake]
        
        if new_lake_id and not new_maskmx_path: # just replace the key
            for d in attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.indexes = list(self.maskmx_file_by_lake.keys())
            
        elif new_maskmx_path and not new_lake_id: # just replace the mask
            self.maskmx_file_by_lake[lake_id] = new_maskmx_path
            
        elif new_lake_id and new_maskmx_path: # replace both the mask and the key
            for d in attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.maskmx_file_by_lake[new_lake_id] = new_maskmx_path
            self.indexes = list(self.maskmx_file_by_lake.keys())


        #%% REMOVE A LAKE/RESERVOIR
        def remove(self, lake_id):
            attr_list = [self.maskmx_file_by_lake, self.mask_crs_by_lake, 
                         self.bathymetry_by_lake, self.bathy_crs_by_lake,
                         self.ssmx_by_lake, self.volmx_by_lake, self.prcplk_by_lake, 
                         self.evaplk_by_lake, self.rnf_by_lake, self.wthdrw_by_lake]
            for d in attr_list:
                d.pop(lake_id)
            
            # Update Lakeres attributes:
            self.indexes = list(self.masks.keys())
            self.n_lakeres = len(self.indexes)
        
        
    #%% UPDATE MAXIMUM STAGES (= WATER LEVELS)
    def update_stagemax(self, lake_id, ssmx):
        self.ssmx_by_lake[lake_id] = ssmx
        
        
    #%% UPDATE FLOWS IN AND OUT OF THE LAKE/RESERVOIR    
    def update_precip(self, lake_id, src):
        self.prcplk_by_lake[lake_id] = src
        
    def update_evap(self, lake_id, src):
        self.evaplk_by_lake[lake_id] = src
        
    def update_runoff(self, lake_id, src):
        self.rnf_by_lake[lake_id] = src
        
    def update_withdraw_fill(self, lake_id, src):
        self.wthdrw_by_lake[lake_id] = src
        
    
   #%% FORMAT ALL ATTRIBUTES INTO INPUTS FOR MODFLOW
    def format_to_modflow(self, geographic, climatic):
        #%%% Standardize lake identifiers
        # -------------------------------
        # lake_id can be anything, defined by the user: 1, 155, 10, 20, ...
        # std_id are: 0, 1, 2...
# =============================================================================
#         std_id_by_lake_id stages = [self.lakeres.ssmx[lake_id] for lake_id in sorted(self.lakeres.ssmx)]
# =============================================================================
        
        #%%% Format lakarr
        # ----------------
        # Load masked np.array of watershed and initialize lakarr
        with rio.open(geographic.watershed_dem, 'r') as base:
            nodata = base.profile['nodata'] # value corresponding to the no data property 
        watershed_mask = toolbox.load_to_numpy(geographic.watershed_dem,
                                               dst_crs = geographic.crs_proj) 
        lakarr = np.ma.array(watershed_mask, 
                            mask = watershed_mask==nodata,
                            fill_value = nodata,
                            ) * 0 # masked np.ndarray with null values
        
        # Load topography
        dem_box = toolbox.load_to_numpy(geographic.watershed_box_buff_dem,
                                        dst_crs = geographic.crs_proj) 
        
        # Cell area
        cell_area = (dem_box.x[1] - dem_box.x[0])*(dem_box.y[0] - dem_box.y[1])        
        
        # Format lakes maskmx (maximal extents)
        for lake_id in self.indexes:
            maskmx = toolbox.load_to_numpy(self.maskmx_file_by_lake[lake_id], 
                                           src_crs = self.mark_crs_by_lake[lake_id],
                                           base_path = geographic.watershed_dem, 
                                           dst_crs = geographic.crs_proj)
        
            maskmx[maskmx == nodata] = 0
            maskmx = maskmx.astype(bool)
            
            if not self.bathymetry_by_lake[lake_id]: # None
            # In this case, topography is used for bathymetry, using the same
            # computation as in the next case
                self.bathymetry_by_lake[lake_id] = geographic.watershed_dem
            
            if os.path.isfile(self.bathymetry_by_lake[lake_id]):
                bathymetry = toolbox.load_to_numpy(
                    self.bathymetry_by_lake[lake_id], 
                    src_crs = self.bathy_crs_by_lake[lake_id],
                    base_path = geographic.watershed_dem, 
                    dst_crs = geographic.crs_proj)
                
                # Replace topo by bathy, on the area where bathy exists:
                dem_box = np.where(bathymetry == nodata, dem_box, bathymetry)
                
                # Update dem files:
                print("Il faut update les DEM files !")
                self.update_dem()
                
                # Mask dem_box with maskmx:
                masked_dem = np.ma.array(dem_box, 
                                         mask = maskmx,
                                         fill_value = nodata,
                                         )
                
                if self.volmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # volmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    print(f"\nComputing the maximum lake/reservoir level to match with a volume of {self.volmx_by_lake[lake_id]} m3")
                    height = np.arange(masked_dem.min(), masked_dem.max(), 0.1)
                    h = 0
                    vol = 0
                    while vol < self.volmx_by_lake[lake_id]:
                        h+=1
                        vol = height[h] - np.ma.where(masked_dem <= height[h],
                                                      masked_dem).sum()*cell_area
                        h+=1
                    
                    maskmx = np.where(masked_dem <= height[h-1], 1, 0)
                    maskmx = maskmx.astype(bool)
                    # Update ssmx (might be used in other functions)
                    self.ssmx_by_lake[lake_id] = height[h-1]
                
                elif self.ssmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # ssmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    maskmx = np.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
                    maskmx = maskmx.astype(bool)
                    
                # If no volmx nor ssmx is defined:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at his maximum extent.
                    
            elif self.bathymetry_by_lake[lake_id] == 'cuboid':
            # In this case, bathymetry will be computed, based on volmx (required)
            # and ssmx (optional)
                if self.volmx_by_lake[lake_id]:
                    if self.ssmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # volmx and ssmx.
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                        print(f"\nComputing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum level of {self.ssmx_by_lake[lake_id]} m")
                        maskmx = np.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
                        maskmx = maskmx.astype(bool)
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem_box = np.where(maskmx, self.ssmx_by_lake[lake_id] - depth, dem_box)
                        
                    else:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at his maximum extent.
                        print(f"\nComputing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum extent")
                        self.ssmx_by_lake[lake_id] = maskmx.max() # Update ssmx (might be used in other functions)
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem_box = np.where(maskmx, self.ssmx_by_lak[lake_id] - depth, dem_box)
                        
                else:
                    print("\nErr: Maximum lake/reservoir volume (volmx) is required to compute bathymetry (cuboid mode)")
            
                print("Il faut update les DEM files ! (computed bathy)")
                self.update_dem()
            
                #>>> reprendre ICI<<<
        
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
        data_by_flux = {'PRCPLK': self.prcpl_by_lake, 
                        'EVAPLK': self.evapl_by_lake, 
                        'RNF': self.rnf_by_lake, 
                        'WTHDRW': self.wthdrw_by_lake}
        attr_flux_list = [self.prcpl_by_lake, self.evapl_by_lake,
                          self.rnf_by_lake, self.wthdrw_by_lake]
        flux_frame = pd.DataFrame(
            columns = list(data_by_flux.keys), 
            index = climatic.recharge.index)
        # Final format:
        # {1:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  2:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  3:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list]...}
# =============================================================================
#         for 
# =============================================================================
        if isinstance(src, pd.core.series.Series):
            0
       
        # return stages, lakarr, bdlknc, flux_data
       
   
    #%% UPDATE DEM FILES        
    def update_dem():
        0
        

    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
