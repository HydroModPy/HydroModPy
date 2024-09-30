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
import datetime
import shutil
import numbers
import pandas as pd
import geopandas as gpd
import numpy as np
import rasterio as rio
import matplotlib.pyplot as plt
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.verbose = False
import xarray as xr
xr.set_options(keep_attrs = True)
wbt = whitebox.WhiteboxTools() # to compute runoff accumulation
wbt.verbose = False
# Alternatively, runoff accumulation could be computed with pyproj. It is 
# expected to be faster as there is no need to write down each time as a file.
# But first it is necessary to solve the uncompatibility between pyproj and
# other modules.
import pyproj
from pysheds.grid import Grid  # to compute runoff accumulation
from pysheds.view import Raster, ViewFinder
from affine import Affine

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
        self.maskmx_by_lake:dict = {} # dict of lakes/reservoirs masks paths, 
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
        self.rnf_acc_by_lake:dict = {}
        self.wthdrw_by_lake:dict = {}
        self.rtrn_by_lake:dict = {} # To connect return flow to SFR
        self.stageinit_by_lake:dict = {} # initial stage
        self.lake_by_num_id:dict = {} # Dict betwen num_id and lake_id
                                      # Defined in self.format_to_modflow()
        self.outlet_by_lake:dict = {}
        self.ij_outlet_by_lake:dict = {}
        

    #%% ADD A NEW LAKE/RESERVOIR   
    def new_lakeres(self, maskmx:str, lake_id:int=None, mask_crs=None,
                    bathymetry_raster:str=None, bathy_crs=None, 
                    ssmx:float=None, volmx:float=None, bdlknc:float=86400, # default = 1 m/s
                    prcplk=0, evaplk=0, rnf=0, rnf_acc=False, wthdrw=0, rtrn=None, 
                    stageinit=None, outlet=None,
                    ):
        """
        Note that lakeres can be a lake or a reservoir.
        
        Parameters
        ----------
        All values should be expressed in the spatial and temporal units of the
        model.
        
        maskmx : str
            Path to the mask file (shapefile or raster).
            Works with NetCDF files?
        lake_id : optional
            DESCRIPTION. The default is None.
        mask_crs : TYPE, optional
            DESCRIPTION. The default is None.
        bathymetry_raster : str, optional
            DESCRIPTION. The default is None.
        bathy_crs : TYPE, optional
            DESCRIPTION. The default is None.
        ssmx : float, optional
            Maximal stage (level) of the lake/reservoir
            The default is None.
        volmx : float, optional
            Maxaimal volume of the lake. 
            The default is None.
        bdlknc : float, optional
            DESCRIPTION. The default is 86400 m/d (= 1 m/s)
        prcplk : float|array|file_path(str), optional
            Input for precipitations on the lake/reservoir. The default is 0 m/d 
            As for the next 3 parameters, prcplk can be defined by a
                - float: same value for all periods
                - pd.DataFrame: with times as index. Choosen times should also
                be present in watershed.climatic
                - file path: a .csv array or a .tif map or a .nc space-time array
        evaplk : float|array|file_path(str)|mode(str), optional
            Input for evaporation from the lake/reservoir. The default is 0 m/d
            As for the next parameter, evaplk can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic < 0.
        rnf : float|array|file_path(str)|mode(str), optional
            Input for runoff to the lake/reservoir. The default is 0 m/d
            As for the previous parameter, rnf can also be defined by the 
            string indicator 'from_climatic': values are extracted from 
            watershed.climatic.runoff.
        rnf_acc : bool (optional)
            A flag to indicate whether the <rnf> value will be:
                . [False] used by Modflow as it is (positive value = volumetric 
                  rate, negative value = dimensionless multiplier)
                . [True] interpreted as a rate per unit area that will be 
                  accumulated to raise a volumetric rate added to the lake.
            The default value is False.
        wthdrw : float|array|file_path(str), optional
            Input for anthropic fluxes on the lake (withdrawal and filling). 
            The default is 0 m/d
            wthdrw integrates the sum of water removal (positive values) and
            water addition (negative values).
        rtrn : timesries, optional
            Return flow at the outlet(s) of each lake. This value is injected
            into the StreamFLow Routing network. It is not withdrawn from the
            lake/reservoir (for that, the return flow should be specified as
            well in wthdrw).
        outlet : str (optional)
            Filepaths to outlet file (shapfile, txt with coordinates)
        

        Returns
        -------
        None.

        """
        
        # Store/infer lake_id
        if lake_id in self.indexes:
            print(f"\nErr: Lake/reservoir with id {lake_id} already exists.")
            return
        if not lake_id:
            if self.n_lakeres == 0:
                lake_id:int = 0 # initialization
            else:
                lake_id:int = np.max(self.indexes) + 1
        print(f"Adding lake '{lake_id}'")
        
        # Lake/reservoir geometry
        self.maskmx_by_lake[lake_id] = maskmx
        self.mask_crs_by_lake[lake_id] = mask_crs
        self.bathymetry_by_lake[lake_id] = bathymetry_raster
        self.bathy_crs_by_lake[lake_id] = bathy_crs
        self.ssmx_by_lake[lake_id] = ssmx
        self.volmx_by_lake[lake_id] = volmx

        # Lake/reservoir parameters
        self.bdlknc_by_lake[lake_id] = bdlknc # default = 1 m/s
        self.stageinit_by_lake[lake_id] = stageinit
        self.outlet_by_lake[lake_id] = outlet
        
        # Lake/reservoir inflows and outflows
        self.prcplk_by_lake[lake_id] = prcplk
        self.evaplk_by_lake[lake_id] = evaplk
        self.rnf_by_lake[lake_id] = rnf
        self.rnf_acc_by_lake[lake_id] = rnf_acc
        self.wthdrw_by_lake[lake_id] = wthdrw
        self.rtrn_by_lake[lake_id] = rtrn

        # Update Lakeres attributes:
        # self.idlist = self.idlist.append(lake_id)
        self.indexes = list(self.maskmx_by_lake.keys())
        self.n_lakeres = len(self.indexes)
        
        # List of attributes
        self.attr_list = [self.maskmx_by_lake, self.mask_crs_by_lake, 
                          self.bathymetry_by_lake, self.bathy_crs_by_lake,
                          self.ssmx_by_lake, self.volmx_by_lake, 
                          self.bdlknc_by_lake, self.stageinit_by_lake,
                          self.outlet_by_lake, self.prcplk_by_lake, 
                          self.evaplk_by_lake, self.rnf_by_lake,
                          self.rnf_acc_by_lake, self.wthdrw_by_lake, 
                          self.rtrn_by_lake]
        
        
    #%% UPDATE A PREVIOUS LAKE/RESERVOIR
    def update_definition(self, lake_id, new_lake_id:int=None, new_maskmx_path:str=None):
        if new_lake_id and not new_maskmx_path: # just replace the key
            for d in self.attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.indexes = list(self.maskmx_by_lake.keys())
            
        elif new_maskmx_path and not new_lake_id: # just replace the mask
            self.maskmx_by_lake[lake_id] = new_maskmx_path
            
        elif new_lake_id and new_maskmx_path: # replace both the mask and the key
            for d in self.attr_list:
                d[new_lake_id] = d.pop(lake_id)
            self.maskmx_by_lake[new_lake_id] = new_maskmx_path
            self.indexes = list(self.maskmx_by_lake.keys())


    #%% REMOVE A LAKE/RESERVOIR
    def remove(self, lake_id):
        for d in self.attr_list:
            d.pop(lake_id)
        
        # Update Lakeres attributes:
        self.indexes = list(self.maskmx_by_lake.keys())
        self.n_lakeres = len(self.indexes)
        
        
    #%% UPDATE GEOMETRY and PHYSICAL PROPERTIES OF THE LAKE/RESERVOIR
    def update_stagemax(self, lake_id, ssmx):
        self.ssmx_by_lake[lake_id] = ssmx
        
    def update_volumemax(self, lake_id, volmx):
        self.volmx_by_lake[lake_id] = volmx
        
    def update_stageinit(self, lake_id, stageinit):
        self.stageinit_by_lake[lake_id] = stageinit
        
    def update_lakebed_leakance(self, lake_id, bdlknc):
        self.bdlknc_by_lake[lake_id] = bdlknc
        
    def update_bathymetry(self, lake_id, bathymetry_raster):
        self.bathymetry_by_lake[lake_id] = bathymetry_raster
        
    def update_outlet(self, lake_id, outlet_file):
        self.outlet_by_lake[lake_id] = outlet_file
        
    #%% UPDATE FLOWS IN AND OUT OF THE LAKE/RESERVOIR    
    def update_precip(self, lake_id, src):
        self.prcplk_by_lake[lake_id] = src
        
    def update_evap(self, lake_id, src):
        self.evaplk_by_lake[lake_id] = src
        
    def update_runoff(self, lake_id, src, runoff_accumulation=False):
        self.rnf_by_lake[lake_id] = src
        self.rnf_acc_by_lake[lake_id] = runoff_accumulation
        
    def update_withdraw_fill(self, lake_id, src):
        self.wthdrw_by_lake[lake_id] = src
    
    def connect_returnflow(self, lake_id, timeseries):
        self.rtrn_by_lake[lake_id] = timeseries
    
   #%% FORMAT ALL ATTRIBUTES INTO INPUTS FOR MODFLOW
    def format_to_modflow(self, geographic, climatic, nper, thickfact, dem, dem_path):
        print("\nLakes/Reservoirs: formating all attributes...")
        
        #%%% Standardize lake identifiers
        # -------------------------------
        # lake_id can be anything, defined by the user: 1, 10, 'lake 155', 'Cheze', ...
        # num_id are: 1, 2, 3...
        self.lake_by_num_id = {idx+1: self.indexes[idx] for idx in range(0, self.n_lakeres)}
        # self.lake_by_num_id = {idx+1: sorted(self.indexes)[idx] for idx in range(0, self.n_lakeres)}
        
        
        #%%% Format lakarr
        # ----------------
        # Load masked np.array of watershed and initialize lakarr
        with rio.open(geographic.watershed_dem, 'r') as base:
            nodata = base.profile['nodata'] # value corresponding to the no data property         
            transform = base.profile['transform']
        watershed_mask, _, _, _ = toolbox.load_to_numpy(geographic.watershed_dem,
                                                        dst_crs = geographic.crs_proj) 
        lakarr = np.ma.array(watershed_mask, 
                            mask = watershed_mask==nodata,
                            fill_value = nodata,
                            ) * 0 # masked np.ndarray with null values
        
# =============================================================================
#         # Load topography
#         dem, _, _, _ = toolbox.load_to_numpy(geographic.watershed_box_buff_dem,
#                                                 dst_crs = geographic.crs_proj) 
# =============================================================================
        
        # Cell area
# =============================================================================
#         cell_area = (dem[0,1] - dem[0,0])*(dem[1,0] - dem[0,0])   
#         cell_area = abs(transform[0]) * abs(transform[4])
# =============================================================================
        cell_area = geographic.cell_size
        
        # Format lakes maskmx (maximal extents)
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            
            maskmx, src_crs, _, _ = toolbox.load_to_numpy(
                self.maskmx_by_lake[lake_id], 
                src_crs = self.mask_crs_by_lake[lake_id],
                base_path = geographic.watershed_dem, 
                dst_crs = geographic.crs_proj)
            
            if self.mask_crs_by_lake[lake_id] is None:
                self.mask_crs_by_lake[lake_id] = src_crs
            
            maskmx[maskmx == nodata] = 0
            maskmx = maskmx.astype(bool)
            
            if not self.bathymetry_by_lake[lake_id]: # None
            # In this case, topography is used for bathymetry, using the same
            # computation as in the next case
                self.bathymetry_by_lake[lake_id] = geographic.watershed_dem
                self.bathy_crs_by_lake[lake_id] = geographic.crs_proj
            
            if os.path.isfile(self.bathymetry_by_lake[lake_id]):
                bathymetry, _, _, _ = toolbox.load_to_numpy(
                    self.bathymetry_by_lake[lake_id], 
                    src_crs = self.bathy_crs_by_lake[lake_id],
                    base_path = geographic.watershed_dem, 
                    dst_crs = geographic.crs_proj)
                
                # Replace topo by bathy, on the area where bathy exists:
                dem = np.where(bathymetry == nodata, dem, bathymetry)
                
                # Update dem files:
                self.update_dem(geographic, dem)
                
                # Mask dem with maskmx:
                masked_dem = np.ma.array(dem, 
                                         mask = ~maskmx,
                                         fill_value = nodata,
                                         )
                
                if self.ssmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # ssmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    maskmx = np.ma.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
                    maskmx = maskmx.astype(bool)
                    if maskmx.sum() == np.ma.count(masked_dem):
                        print(f" Warning: The lake maximal level (ssmx) is likely to be too small. It can not naturally exceed {masked_dem.max()} m. To match the required ssmx of {self.ssmx_by_lake[lake_id]} m, the lake surface was considered not continuous with the surrounding topography.")
                    
                    if self.volmx_by_lake[lake_id]:
                        masked_dem = np.ma.array(dem, 
                                                 mask = ~maskmx,
                                                 fill_value = nodata,
                                                 )
                        equiv_vol = float((self.ssmx_by_lake[lake_id] - masked_dem).sum()*cell_area)
                        print(f" The specified maximal volume ({self.volmx_by_lake[lake_id]} m3) is discarded because redundant with the specified maximal level (equiv. to {equiv_vol} m3)")
                        self.volmx_by_lake[lake_id] = equiv_vol
                        
                
                elif self.volmx_by_lake[lake_id]:
                    # In this case, maskmx will be adjusted to match the desired
                    # volmx. 
                    # In this situation, maskmx is to be considered as an enlarged
                    # maximal potential extent of the lake, similar to the mask
                    # of the valley around the lake.
                    print(f" Computing the maximum lake/reservoir level to match with a volume of {self.volmx_by_lake[lake_id]} m3")
                    # elev = np.arange(masked_dem.min(), masked_dem.max(), 0.1)
                    i = 0
                    vol = 0
                    elev = masked_dem.min()
                    while vol < self.volmx_by_lake[lake_id]:
                        vol = (elev - np.ma.where(masked_dem <= elev,
                                                      masked_dem, elev)).sum()*cell_area
                        elev+=0.1
                        i+=1
                    if elev > masked_dem.max():
                        nat_vol = (masked_dem.max() - np.ma.where(masked_dem <= masked_dem.max(),
                                                      masked_dem, masked_dem.max())).sum()*cell_area
                        print(f" Warning: The lake maximal extent (maskmx) is likely to be too small. It can only naturally contain a volume of {nat_vol} m3. To match the required volmx of {self.volmx_by_lake[lake_id]} m3, the lake surface was considered not continuous with the surrounding topography.")
                    
                    maskmx = np.ma.where(masked_dem <= elev-0.1, 1, 0)
                    maskmx = maskmx.astype(bool)
                    # Update ssmx (might be used in other functions)
                    self.ssmx_by_lake[lake_id] = elev-0.1

                    
                # If no volmx nor ssmx is defined:
                else:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at its maximum extent.
                    print(f" Warning: The '{lake_id}' lake/reservoir mask will be used as a strict mask of the lake at its maximum extent.")
                    self.ssmx_by_lake[lake_id] = masked_dem.max() # Update ssmx (might be used in other functions)
                    
                    
            elif self.bathymetry_by_lake[lake_id] == 'cuboid':
            # In this case, bathymetry will be computed, based on volmx (required)
            # and ssmx (optional)
                if self.volmx_by_lake[lake_id]:
                    if self.ssmx_by_lake[lake_id]:
# =============================================================================
#                     # In this case, maskmx will be adjusted to match the desired
#                     # volmx and ssmx.
#                     # In this situation, maskmx is to be considered as an enlarged
#                     # maximal potential extent of the lake, similar to the mask
#                     # of the valley around the lake.
# =============================================================================
                    # In this case, maskmx will be used as a strick mask of the
                    # lake/reservoir, at its maximal extent.
                        print(f" Computing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum level of {self.ssmx_by_lake[lake_id]} m")
                        # The commented following part is about adjusting the lake extent, using ssmx
# =============================================================================
#                         maskmx = np.ma.where(masked_dem <= self.ssmx_by_lake[lake_id], 1, 0)
#                         maskmx = maskmx.astype(bool)
# =============================================================================
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem = np.where(maskmx, self.ssmx_by_lake[lake_id] - depth, dem)
                        
                    else:
                    # In this case, maskmx will be used as a strict mask of the
                    # lake/reservoir, at its maximum extent.
                        print(f" Computing the bathymetry to match the defined maximum volume of {self.volmx_by_lake[lake_id]} m3 and maximum extent")
                        self.ssmx_by_lake[lake_id] = masked_dem.max() # Update ssmx (might be used in other functions)
                        depth = self.volmx_by_lake[lake_id] / maskmx.sum()*cell_area
                        dem = np.where(maskmx, self.ssmx_by_lake[lake_id] - depth, dem)
                        
                else:
                    print(" Err: Maximum lake/reservoir volume (volmx) is required to compute bathymetry (cuboid mode)")
            
                self.update_dem(geographic, dem)
        
# =============================================================================
#             lakarr = lakarr + np.ma.array(maskmx,
#                                           fill_value = nodata
#                                           ) * lake_id
# =============================================================================
            maskmx = np.ma.array(maskmx,
                                 mask = watershed_mask==nodata,
                                 fill_value = nodata
                                 )
    
            # Check overlapping between lakes
            for num_id2 in self.lake_by_num_id.keys():
                lake_id2 = self.lake_by_num_id[num_id2]
                temp_lakarr = lakarr.copy()*0
                temp_lakarr[lakarr==num_id2] = 1
                intersect = (maskmx*temp_lakarr).sum()
                if intersect > 0:
                    print(f" Warning: Lake '{lake_id}' will overwrite lake '{lake_id2}' on {int(intersect)} cells.")
        
            lakarr[maskmx==1] = num_id
            
        # Convert the masked array into an array
        lakarr = lakarr.filled(0)
        
# =============================================================================
#             lakarr = np.where(maskmx==1, lake_id, lakarr)
# =============================================================================
    
# A SUPPRIMER BIENTOT !    
# =============================================================================
#         # Check overlapping between lakes   
#         if geographic:     
#             with rio.open(geographic.watershed_dem, 'r') as base:
#                 nodata = base.profile['nodata'] # value corresponding to the no data property 
# 
#             maskmx = toolbox.load_to_numpy(maskmx_path, 
#                                          src_crs = src_crs,
#                                          base_path = geographic.watershed_dem, 
#                                          dst_crs = geographic.crs_proj)
#             
#             maskmx[maskmx == nodata] = 0
#             
#             for idx in self.indexes:
#                 prev_maskmx = toolbox.load_to_numpy(maskmx_path, 
#                                                     src_crs = src_crs,
#                                                     base_path = geographic.watershed_dem, 
#                                                     dst_crs = geographic.crs_proj)
#                 
#                 intersect = (maskmx*prev_maskmx).sum()
#                 if intersect > 0:
#                     print(f"\n NB: Lake n°{lake_id} may overwrite lake n°{idx} on {int(intersect)} cells.")
#         
# =============================================================================

        # Export
        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'lakarr.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, lakarr.astype(int))
            
        #%%% Format the top of the lake/reservoir layer
        # ---------------------------------------------
        laklay_top = dem.copy()+1
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            laklay_top[lakarr == num_id] = self.ssmx_by_lake[lake_id]
            # laklay_top[(lakarr == num_id) & (laklay_top < thickfact*100)] = thickfact*100
            # laklay_top[(laklay_top - dem) < thickfact*100] = laklay_top + thickfact*100
            laklay_top = np.where(laklay_top < dem + thickfact*100, dem + thickfact*110, laklay_top)
            
        # Exports
        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'laklay_top.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, laklay_top)

        with rio.open(geographic.watershed_dem, 'r') as base:
            base_profile = base.profile
            base_profile['crs'] = geographic.crs_proj
            # base_profile['nodata'] = 0
            # base_profile['dtype'] = int
        with rio.open(os.path.join(self.data_folder, 'laklay_thick.tif'),
                      'w', **base_profile) as dst: 
            dst.write_band(1, laklay_top - dem)
        
            
        #%%% Format initial stage
        # -----------------------
        stages = []
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            if isinstance(self.stageinit_by_lake[lake_id], (int, float)):
                stages.append(self.stageinit_by_lake[lake_id])
            else:
                print(f" Warning: The lake/reservoir '{lake_id}' will be initially considered dry.")
                stages.append(float(dem[maskmx==1].min()))
                
        #%%% Format bedlake leakance
        # --------------------------
        # bdlknc = {}
        # for kper in range(0, nper):
        #     bdlknc_val = []
        #     for num_id in self.lake_by_num_id.keys():
        #         lake_id = self.lake_by_num_id[num_id]
        #         bdlknc_val.append(self.bdlknc_by_lake[lake_id])
        #     bdlknc[kper] = bdlknc_val
        bdlknc = lakarr.copy()*0 + self.bdlknc_by_lake[lake_id]
        
        #%%% Format outlets
        self.format_outlets(lakarr, geographic, dem_path)
        
        #%%% Format fluxes data
        # ---------------------
        flux_data = {kper:[] for kper in range(0, nper)}
        settings_by_flux = {'PRCPLK': self.prcplk_by_lake, 
                        'EVAPLK': self.evaplk_by_lake, 
                        'RNF': self.rnf_by_lake, 
                        'WTHDRW': self.wthdrw_by_lake}
        # Final format:
        # {0:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  1:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  2:[PRCPLK:list, EVAPLK:list, RNF:list, WTHDRW:list],
        #  ...}
            
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            lake_frame = pd.DataFrame(
                columns = list(settings_by_flux.keys()), 
                index = climatic.index)
        
            for flux in settings_by_flux.keys():
                settings = settings_by_flux[flux][lake_id]
            
                # Constant value: same for all periods
                if isinstance(settings, numbers.Number):
                    if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                        pd_data = self.accumulate_runoff(settings, lake_id, geographic)
                        lake_frame.loc[pd_data.index, flux] = pd_data
                    else:
                        lake_frame[flux] = settings
                
                else:
                    if isinstance(settings, str):
                        # If flux is defined by 'from_climatic' option
                        if settings == 'from_climatic':
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                try: 
                                    pd_data = self.accumulate_runoff(climatic.runoff, 
                                                                     lake_id, 
                                                                     lakarr,
                                                                     geographic)
                                    # flux_frame.loc[climatic.runoff.index, num_id] = climatic.runoff
                                except: 
                                    print(f" Err: {flux} over lake '{lake_id}' cannot be defined from climatic: watershed.climatic.runoff does not exist")
                                    return
                            elif flux == 'EVAPLK':
                                pd_data = -climatic.where(climatic<0, 0)
                                # flux_frame.loc[:, num_id] = -climatic.where(
                                #     climatic<0, 0)
                            else:
                                print(f" Err: {flux} over lake '{lake_id}' cannot be defined from climatic")
                                return
                        
                        # Array file (.csv or .txt): will be read with pandas
                        elif os.path.isfile(settings) & os.path.splitext(settings)[-1].casefold() in ['.csv', '.txt']:
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                pd_data = self.accumulate_runoff(
                                    pd.read_csv(settings, sep=';', index_col=0, parse_dates=True),
                                    lake_id, lakarr, geographic)
                            else:
                                pd_data = pd.read_csv(settings, sep=';', index_col=0, parse_dates=True)
                            
                        # NetCDF file: will be read with xarray
                        elif os.path.isfile(settings) & os.path.splitext(settings)[-1].casefold() == '.nc':
                            ds = toolbox.read_with_xarray(settings)
                            if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                                pd_data = self.accumulate_runoff(ds, lake_id, lakarr, geographic)
                            else:
                                # xarray.DataSet: spatial mean over the lake area is extracted to a pandas.DataFrame
                                print("xr.DataSet needs to be converted into pd.DataFrame (not implemented yet)")
                            
                    # Format df to flux_frame
                    if isinstance(settings, pd.DataFrame):
                    # Convert pandas.DataFrame to pandas.Series
                        if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                            pd_data = self.accumulate_runoff(settings, lake_id, lakarr, geographic)
                        else:
                            pd_data = settings[settings.columns[0]]
                    elif isinstance(settings, pd.Series):
                        if (flux == 'RNF') & (self.rnf_acc_by_lake[lake_id] == True):
                            pd_data = self.accumulate_runoff(settings, lake_id, lakarr, geographic)
                        else:
                            pd_data = settings
                    
                    # pd_data.set_index(pd_data.index.normalize()) 
                    pd_data.index = pd_data.index.normalize() # To convert dates-time to midnight.
                    pd_data = pd_data[(pd_data.index >= climatic.index[0]) & (pd_data.index <= climatic.index[-1])]
                    lake_frame.loc[pd_data.index, flux] = pd_data
                    lake_frame[flux].fillna(method = 'ffill', inplace = True) # forward fill
                    lake_frame[flux].fillna(0, inplace = True) # replace remaining NaN with 0
            
            for kper in range(0, nper):
                flux_data[kper].append(lake_frame.iloc[kper].to_list())
            
            # export
            lake_frame.to_csv(os.path.join(self.data_folder,
                                           f"flux_data_lake_{lake_id}.csv"), 
                              sep = ';', 
                              header = True) 
                
        print('\n')
        return stages, lakarr, laklay_top, bdlknc, flux_data, dem
       
   
    #%% UPDATE DEM FILES        
    def update_dem(self, geographic, dem):
        # dem has been modified, and its modifications should also be applied
        # on all dem files.
        print("Updating DEM files...")
        # Update DEM initial file
        # bathy_dem = os.path.join(geographic.reg_path, 'temp_DEM_with_bathymetry.tif')
        filepath, ext = os.path.splitext(geographic.dem_path)
        shutil.copy2(geographic.dem_path, filepath + '_temp' + ext)
        with rio.open(geographic.dem_path, 'r+') as bathy_dem:
            with rio.open(geographic.watershed_box_buff_dem, 'r') as box:
                window = rio.windows.from_bounds(*box.bounds, transform=bathy_dem.transform)
                bathy_dem.write_band(1, dem, window=window)
            
        geographic.processing()
        
        os.remove(geographic.dem_path)
        os.rename(filepath + '_temp' + ext, geographic.dem_path)
        

    #%% FORMAT OUTLETS
    def format_outlets(self, lakarr, geographic, dem_path):
        self.ij_outlet_by_lake = {}
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            file = self.outlet_by_lake[lake_id]
            if file is None:
                # Automatic detection of the outlet (cell with the highest accumulation flow)
                acc_map, _, _, nodata = toolbox.load_to_numpy(
                    os.path.join(geographic.reg_path, 'region_acc.tif'), 
                    src_crs = geographic.crs_proj, 
                    base_path = dem_path, 
                    dst_crs = geographic.crs_proj)
# =============================================================================
#                 watershed_mask, _, _, nodata = toolbox.load_to_numpy(
#                     dem_path,
#                     src_crs = self.geographic.crs_proj, 
#                     base_path = dem_path,
#                     dst_crs = self.geographic.crs_proj)
# =============================================================================
                acc_map = np.ma.array(
                    acc_map, 
                    mask = lakarr!=num_id, 
                    fill_value = nodata) # masked np.ndarray
                
                i, j = np.unravel_index(np.argmax(acc_map), acc_map.shape)
 
            else:
                arr, _, _, _ = toolbox.load_to_numpy(
                    file,
                    src_crs = self.mask_crs_by_lake[lake_id],
                    base_path = geographic.watershed_dem, 
                    dst_crs = geographic.crs_proj)
                
                i = np.argwhere(arr==num_id)[0,0] 
                j = np.argwhere(arr==num_id)[0,1]
            
            self.ij_outlet_by_lake[lake_id] = (i, j)
        
        # Export lake outlet
        outlet_map = acc_map.copy()
        outlet_map[:]= nodata
        for num_id in self.lake_by_num_id.keys():
            lake_id = self.lake_by_num_id[num_id]
            outlet_map[self.ij_outlet_by_lake[lake_id][0],
                       self.ij_outlet_by_lake[lake_id][1]
                       ] = num_id
        toolbox.export_tif(
            geographic.watershed_dem,
            outlet_map, 
            geographic.nodata, 
            os.path.join(self.data_folder, "lak_outlets.tif"))
        
# =============================================================================
#         return self.ij_outlet_by_lake
# =============================================================================
                
    #%% ACCUMULATE RUNOFF
    def accumulate_runoff(self, data, lake_id, lakarr, geographic):
        """
        Compute the accumulated runoff entering a lake/reservoir, from a runoff 
        input (single value, .csv or .txt file, timeseries or dataframe, NetCDF 
        file...). The result is a dataframe that will be used to fill the
        data_flux for flopy.modflow.ModflowLak().
        
        Note: runoff input has to be a VOLUME time series ([L]**3/[T])

        Parameters
        ----------
        data : xr.Dataset/xr.DataArray, pd.DataFrame/pd.Series, Number
            Runoff input.
            The conversion from file (.txt, .csv, .nc) to variable is made
            beforehand in format_to_modflow(), before calling accumulat_runoff()
            function.
        lake_id : str, int
            Identifier of the lake/reservoir. It is defined by user when 
            initializing the lake/reservoir.
        lakarr : np.array
            Array containing the value 0 everywhere except on lake/reservoir
            locations, where the value is equal to the num_id of the lake/res.
            (num_id is the number of the lake/reservoir, starting from 1, taken
             as the numeric identifier equivalent of the lake_id identifier)
        geographic : object
            Watershed object built by HydroModPy (model domain)

        Returns
        -------
        A pandas.dataframe containing the timeseries of accumulated runoff
        entering the lake identified by 'lake_id'.
        This function also generates a NetCDF file with the accumulated runoff
        values, that can be used by user in the post-processing to sum it to 
        the surface flow values computed by HydroModPy.

        """
        
        # ---- Initialize
        # Create mask of watershed: =0 on lakes/reservoirs, =1 everywhere else
        mask = np.where(lakarr > 0, 0, 1)
        
        # Get time coordinate
        if isinstance(data, (pd.DataFrame, pd.Series)):
            # if data.index are dates...
            if isinstance(data.index[0], (datetime.datetime, 
                                          pd.Timestamp, 
                                          np.datetime64,
                                          str)):          
                # ...then the index is used as the time coordinate
                time = data.index
        # If data has no index, or no date index...
        else:       
            # ...then the tim coordinate is built as a 0, 1, 2, 3... array
            # time = pd.Series(range(len(self.recharge)), index=range(len(self.recharge)))
            time = np.array(range(len(data)))
            # In that case, data is formatted to a pd.dataframe
            data = pd.DataFrame(data = data, index = time, columns = 'runoff')

        # Build space coordinates
        x = [x for x in np.arange(
            geographic.xmin + geographic.resolution_x/2, 
            geographic.xmin + geographic.resolution_x*mask.shape[1] + geographic.resolution_x/2, 
            geographic.resolution_x)]
        y = [y for y in np.arange(
            geographic.ymax + geographic.resolution_y/2, 
            geographic.ymax + geographic.resolution_y*mask.shape[0] + geographic.resolution_y/2, 
            geographic.resolution_y)]
        
        # Generate a xarray.DataArray of runoff: data_4D
        units = ''
        # If data is already a xr.dataarray, no operation is needed
        if isinstance(data, xr.DataArray):
            data_4D = data
            units = data.attrs['units'].copy()
        
        # if data is a xr.dataset, the corresponding xr.dataarray is extracted
        elif isinstance(data, xr.Dataset):
            main_var = list(data.data_vars)[0]
            data_4D = data[main_var]
            units = data[main_var].attrs['units'].copy()
        
        # if data is something else, a xr.dataarray will be built from scratch
        else:
            # Create an empty dataarray
            data_4D = xr.DataArray(coords=[time, y, x], dims=["time", "y", "x"])
            # if data is a single number, it is used to fill the xr.dataarray
            if isinstance(data, numbers.Number):
                data_4D[:] = data
            # if data is a pd.dataframe, it is used to fill the xr.dataarray for each time
            elif isinstance(data, pd.DataFrame):
                for t in time:
                    data_4D.loc[{'time': t}] = data.loc[t].iloc[0] # value of the column 0 at the time t
            elif isinstance(data, pd.Series):
                for t in time:
                    data_4D.loc[{'time': t}] = data.loc[t] # value at the time t
        
        # Set runoff values over the extent of all lake/reservoirs to 0
        # (no runoff over water surfaces)
        # Note that, in the place of runoff, the precipitations falling directly on
        # lakes/reservoirs are expected to be user-defined as the 'PRCPLK' flux (self.prcplk_by_lake)
        data_4D = data_4D.where(np.tile(mask, (len(time), 1, 1)) == 1, 0)
        
        # ---- Compute accumulated mass flow in every cell
        # With pyproj (no need to write&read files as with whitebox)
        direc, _, _, _ = toolbox.load_to_numpy(
            geographic.watershed_box_buff_direc)
        # Cancel flow direction in lake outlet
        # Here we consider that the runoff can accumulate over the lake (in
        # order to compute the accumulated runoff value), but it can not leave the lake.
        for l in self.ij_outlet_by_lake: # for each lake on the watershed
            (i_, j_) = self.ij_outlet_by_lake[l]
            direc[i_, j_] = 0
        # Create a pysheds.grid object with flow directions
        direc_raster = Raster(direc)
        direc_raster.crs = geographic.crs_proj
        direc_raster.nodata = -1 # geographic.nodata
        direc_raster.affine = Affine(
            geographic.resolution_x, 0, geographic.xmin,
            0, geographic.resolution_y, geographic.ymax)
        grid = Grid.from_raster(direc_raster,
                                data_name='direc')
        
        for t in data_4D.time:
            # Create a pysheds.raster object with runoff values
            weights = data_4D.loc[{'time': t}].copy(deep = True)
            # Runoff values are normalized into weights
            weights_norm = weights/weights.sum() # normalize
            weights_raster = Raster(weights_norm.values)
            weights_raster.crs = geographic.crs_proj
            weights_raster.nodata = geographic.nodata
            weights_raster.affine = Affine(
                geographic.resolution_x, 0, geographic.xmin,
                0, geographic.resolution_y, geographic.ymax)
            # Specify directional mapping
            dirmap = (128, 1, 2, 4, 8, 16, 32, 64)       #D8 wbt system
            # Calculate flow accumulation based on flow directions weighted by runoff values
            acc = grid.accumulation(
                direc_raster,
                weights = weights_raster,
                dirmap = dirmap)
            # Remove the normalization to obtain the absolute accumulated values
            acc = acc * weights.sum().item() # denormalize
            data_4D.loc[{'time': t}] = np.array(grid.view(acc))
            
            
            # Alternative way with whitebox (WBT) (Notes)
# =============================================================================
#             im = imageio.imread(self.raw_rast_path)
#             im[im<0] = 0
#             toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.load_rast_path)
#             ### Efficiency ###
#             im = imageio.imread(self.watershed_buff_fill_surflow)
#             im[im>=0] = 1
#             toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.eff_rast_path)        
#             ### Adsorption ###
#             im = imageio.imread(self.watershed_buff_fill_surflow)
#             im[im>=0] = 0
#             toolbox.export_tif(self.watershed_buff_fill_surflow, im, -99999, self.abs_rast_path)
#             ### d8massflux ###
#             wbt.d8_mass_flux(self.watershed_buff_fill_surflow,
#                              self.load_rast_path, self.eff_rast_path,
#                              self.abs_rast_path, self.mass_rast_path)
# =============================================================================
        
        # ---- Export to a netcdf file in the pre-processing folder
        data_ds = data_4D.to_dataset(name = 'acc_runoff')
        # Attributes
        data_ds.rio.write_crs(geographic.crs_proj, inplace = True)
        data_ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                           'long_name': 'x coordinate of projection',
                           'units': 'Meter'}
        data_ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                           'long_name': 'y coordinate of projection',
                           'units': 'Meter'}
        main_var = list(data_ds.data_vars)[0]
        data_ds[main_var].attrs = {'standard_name': 'runoff',
                                   'long_name': 'surface runoff',
                                   'units': units}
        data_ds.to_netcdf(os.path.join(self.data_folder, f'accumulated_runoff_{lake_id}.nc'))
        
        # ---- Extract the time series in the lake outlet cells into a pandas.Series
        # Get outlet coordinates of the currenet lake
        (i, j) = self.ij_outlet_by_lake[lake_id]
        # (x_out, y_out) = (
        #     geographic.xmin + geographic.resolution_x/2 + geographic.resolution_x*j,
        #     geographic.ymax + geographic.resolution_y/2 + geographic.resolution_y*i
        #     )
        data_pd = data_4D[{'x': j, 'y': i}]
        # data_pd = data_4D.loc[{'x': x_out, 'y': y_out}]
        
        data_pd = data_pd.to_dataframe(name = 'acc_runoff') # convert xr.dataarray to pd.dataframe
        
        return data_pd
        

    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
