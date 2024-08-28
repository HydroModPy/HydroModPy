# -*- coding: utf-8 -*-
"""
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

# HydroModPy
from tools import toolbox

#%% CLASS

class Streamflow_seepage:

    
    #%% INIT
    
    def __init__(self, geographic : object, area=None, icalc:int=0, thickm:float=0.1, 
                 depth:float=0, hcond:float=10, width:float=1, slope:float=0.1,
                 rchlen:float=None, critical_mode=None, 
                 correction_multiple_reaches:bool=False,
                 correction_elevations:bool=True, reach_data=None,
                 segment_data=None):
        
        """
        Class to initialize the streamflow seepage option.

        Parameters
        ----------
        geographic : object
            DESCRIPTION
        area : str, optional
            'river' | 'watershed' | 'domain' | None (default)
            Flag to choose whether the SFR seepage is applied on the main
            river, on the watershed or on the whole modeled domain.
        icalc : integer, optional
            The default is 0 (no computation of flow thickness and width)
        thickm : float, optional
            Average streambed thickness. The default is 0.1.
        depth : float, optional
            Average water depth. The default is 0.
        hcond : float, optional
            Avergae streambed conductivity. The default is 10.
        width : float, optional
            Average channel width. The default is 1.
        slope : float, optional
            The average slope of the streambed. The default is 0.1 (10%).
        rchlen
            length of the channel. The default is the average straight euclidian length.
        critical_mode : str, optional
            A flag or a filepath to indicate which cells are critical for
            convergence and whose conductance should be adapted.
            The default is None. If None, no correction is applied.
        correction_multiple_reaches : bool, optional
            Flag to indicate whether to remove multiple reaches located on the 
            same cell or not.
            The default is False
        correction_elevations : bool, optional
            Flag to indicate whether to correct streambed elevations and slopes
            to avoid any sink or flat zone.
            The default is True
        reach_data : pandas.DataFrame, optional
            The default is None
        segment_data : pandas.DataFrame, optional
            The default is None
            
            

        Returns
        -------
        None.

        """
        
        # ---- Create folder (in 'results_stable')
        self.sfr_seepage_folder = os.path.join(geographic.stable_folder, "sfr_seepage")
        if not os.path.exists(self.sfr_seepage_folder):
            os.makedirs(self.sfr_seepage_folder)
        
        # ---- Initialize parameter values
        self.icalc = 0 # No computation of flow thickness and width
        
        self.thickm = thickm # average streambed thickness
        self.depth = depth # average depth of water in the channel
        self.hcond = hcond # average streambed conductivity
        self.width = width # average channel width
        self.slope = slope # average channel slope
        if rchlen is None: # average channel lenght in each cell
            self.rchlen = geographic.resolution * (1/4 + 1/(2*np.sqrt(2))) # average straight euclidien length
        else:
            self.rchlen = rchlen
            
        self.area = area # area where the SFR seepage will be applied
        
        # Load data or not
        self.load_reach_data = reach_data
        self.load_segment_data = segment_data
        
        self.critical_mode = critical_mode # 
        self.crit_area = None # SHould be defined by calling 
                              # correct_critical_cells() function
        
        self.correction_multiple_reaches = correction_multiple_reaches # Remove double reaches
        self.correction_elevations = correction_elevations # correct elevations and slopes to
                                                           # avoid sinks and flat areae


    #%% Define seepage area where StreamFLow Routing will be applied
    def SFR_seepage_area(self, geographic, dem):
        self.dem = dem
        # Discretization: by default, the number of rows and columns is the DEM discretization
        self.nrow = dem.shape[0]
        self.ncol = dem.shape[1]
        self.resolution = geographic.resolution
        
        # ---- Define the area of SFR seepage
        self.direc, _, _, _ = toolbox.load_to_numpy(geographic.watershed_box_buff_direc)
        
        if self.area == 'river':
        # SFR seepage is only applied on the main river
           
            acc_map, _, _, nodata = toolbox.load_to_numpy(
                os.path.join(geographic.reg_path, 'region_acc.tif'), 
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem, 
                dst_crs = geographic.crs_proj)
            watershed_mask = np.where(acc_map >= 0.1*acc_map.max(), 1, nodata)
            acc_map = np.ma.array(acc_map, 
                                  mask = acc_map <= 0.1*acc_map.max(), 
                                  fill_value = nodata)
            self.direc = np.ma.array(
                self.direc, mask = watershed_mask==nodata, fill_value = nodata) # masked np.ndarray
            # A supprimer
# =============================================================================
#             # 1. Load the accumulation_flux map
#             # acc_map = acc_map[acc_map >= 0.1*acc_map.max()]
#             # acc_map = np.ma.MaskedArray(
#             #     data = acc_map, 
#             #     mask = acc_map <= 0.1*acc_map.max())
#             # 2. Select only the cells with significant flow (10% of flow.max)
#             # acc_map = np.ma.where(acc_map >= 0.1*acc_map.max(), 1, 0) # acc_map = acc_map*0+1
#             # 3. Extract the local drain directions on these cells
#             # self.direc = acc_map*self.direc
# =============================================================================
            
        elif self.area == 'watershed':
        # SFR seepage is applied on the whole watershed
            watershed_mask, _, _, nodata = toolbox.load_to_numpy(
                geographic.watershed_dem,
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem,
                dst_crs = geographic.crs_proj) 
            self.direc = np.ma.array(
                self.direc, mask = watershed_mask==nodata, fill_value = nodata) # masked np.ndarray
            
        elif self.area == 'domain':
        # SFR seepage is applied on the whole domain
            watershed_mask, _, _, nodata = toolbox.load_to_numpy(
                self.dem,
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem,
                dst_crs = geographic.crs_proj)
            self.direc = np.ma.array(
                self.direc, mask = watershed_mask==nodata, fill_value = nodata) # masked np.ndarray


    #%% LOAD REACH AND SEGMENT DATA
    def load_data(self, reach_data, segment_data):
        """
        

        Parameters
        ----------
        reach_data : str, path
            Filepath to the .csv file.
        segment_data : str, path
            Filepath to the .csv file.

        Returns
        -------
        None.

        """
        self.load_reach_data = reach_data
        self.load_segment_data = segment_data
    
    
    #%% UPDATE PARAMETER VALUES
    def update_area(self, area):
        self.area = area
    
    def update_reach_data(self, param_name, param_value):
        # self.reach_data[param_name] = param_value   
        if param_name in ['rchlen']:
            self.rchlen = param_value
        
    def update_segment_data(self, param_name, param_value):
        # self.segment_data_1[param_name] = param_value
        if param_name in ['thickm1', 'thickm2', 'thickm']:
            self.thickm = param_value
        elif param_name in ['depth1', 'depth2', 'depth']:
            self.depth = param_value
        elif param_name in ['hcond1', 'hcond2', 'hcond']:
            self.hcond_max = param_value
        elif param_name in ['width1', 'width2', 'width']:
            self.width = param_value
            
    def correct(self, param_name, param_value):
        if param_name == 'multiple_reaches':            
            self.correction_multiple_reaches = param_value
        if param_name == 'elevations':
            self.correction_elevations == param_value
    
    
    #%% GENERATE REACH AND SEGMENT DATA (LOAD or AUTOMATICALLY COMPUTE)
    def compute_data(self):
        ### Initialize reach and segment info:
         # NOTE: self.reach_data is first created as a pandas.dataframe and then 
         # converted into a numpy.recarray. It is not directly created as a 
         # recarray because of the difficulty to handle and modify recarrays.
         # Same for self.segment_data_1
        
        # ---- Load (if specified)
        if (self.load_reach_data is not None) & (self.load_segment_data is not None):
            if os.path.isfile(self.load_reach_data) & os.path.isfile(self.load_segment_data):
# =============================================================================
#                 # version recarray
#                 self.reach_data = np.genfromtxt(reach_data_path, delimiter=';', names=True)
# =============================================================================
                self.reach_data = pd.read_csv(self.load_reach_data, sep=';')
# =============================================================================
#                 # version reacarray
#                 self.segment_data_1 = np.genfromtxt(segment_data_path, delimiter=';', names=True)
# =============================================================================
                self.segment_data_1 = pd.read_csv(self.load_segment_data, sep=';') 
                
                self.cond_drain = self.segment_data_1['hcond'].mean() \
                    * self.segment_data_1['rchlen'].mean() \
                        * self.segment_data_1['width'] / self.segment_data_1['thickm'].mean()
                
        # ---- Otherwise:
        elif self.area is not None :    
            # ---- Initialize
            self.reach_data = pd.DataFrame(
                index = range(0, (~np.isnan(self.direc)).sum()), 
                              # (~np.isnan(self.direc)).sum(), 
                              # self.direc.count(),
                columns = ['k', 'i', 'j', 'iseg', 'ireach','rchlen', 'strtop', 
                           'slope'])
                
            self.segment_data_1 = pd.DataFrame(columns = ['icalc', 'outseg', 'iupseg',
                                                     'nstrpts', 'flow', 'roughch',
                                                     'roughbk', 'cdpth', 'fdpth',
                                                     'awdth', 'bwdth', 'hcond1',
                                                     'thickm1', 'elevup', 'width1',
                                                     'depth1', 'hcond2', 'thickm2',
                                                     'elevdn', 'width2', 'depth2'])
            # Note: self.segment_data_1 is the data for the 1st stress period
            self.segment_data_1.index.name = 'nseg'
            self.segment_data_1['outseg'] = 0
            self.reach_data['ireach'] = 1
            self.reach_data['iseg'] = 0 # range(1, self.direc.count()+1)
            self.reach_data['slope'] = self.slope
            ilist = [ij[0] for ij, _ in np.ma.ndenumerate(self.direc)]
            jlist = [ij[1] for ij, _ in np.ma.ndenumerate(self.direc)]
            self.reach_data['i'] = ilist
            self.reach_data['j'] = jlist
            
            # Note: k, rchlen, strtop and slope are corrected in the next sections
            
            # ---- Recursive generation of segments and reaches      
            # 1. Convert D8 local direction codes into indexes i and j:
                # Notes: D8 notation from WhiteToolBox differs from the standard D8 notation
                # see https://www.whiteboxgeo.com/manual/wbt_book/available_tools/hydrological_analysis.html#D8Pointer
            downstream_ij_by_val = {
                0: (0, 0), 
                1: (-1, 1), #128 (esri code)
                2: (0, 1), #1 
                4: (1, 1), #2
                8: (1, 0), #4
                16: (1, -1), #8
                32: (0, -1), #16
                64: (-1, -1), #32
                128: (-1, 0), #64
                }
                
            self.upstream_cells_by_ij = {
                (self.reach_data.loc[r, 'i'], self.reach_data.loc[r, 'j']): [] \
                    for r in self.reach_data.index}
            for i, j in self.upstream_cells_by_ij.keys():
                val = self.direc[i, j]
                i2 = i + downstream_ij_by_val[val][0]
                j2 = j + downstream_ij_by_val[val][1]
                    
                # if the downstream cell is part of the valid domain:
                if val != 0:
                    if (i2 <= self.nrow-1) & (i2 >= 0) & (j2 <= self.ncol-1) & (j2 >= 0):
                        if not np.ma.is_masked(self.direc[i2, j2]):
                            self.upstream_cells_by_ij[(i2, j2)] += [(i, j)]
            
            # 2. Get all the outlets
            outlet_map = self.direc.copy()
            outlet_map.mask = True
            
            for ij, val in np.ma.ndenumerate(self.direc):
                i = ij[0]
                j = ij[1]
                i2 = i + downstream_ij_by_val[val][0]
                j2 = j + downstream_ij_by_val[val][1]
                
                if val == 0:
                # all cells with local drain direction = 0 are internal outlets
                    outlet_map.mask[i, j] = False
                elif (i2 > self.nrow-1) | (i2 < 0) | (j2 > self.ncol-1) | (j2 < 0):
                # downstream cell outside of the box domain
                    outlet_map.mask[i, j] = False
                elif self.direc.mask[i2, j2] == True:
                # downstream cell outside of the valid data region
                    outlet_map.mask[i, j] = False
                
            outlets = [ij for ij, _ in np.ma.ndenumerate(outlet_map)]    
            
            # 3. Definition of the recursive function
            def stream_reconstruct(ij_outlet, last_iseg):            
                self.segment_data_1.loc[last_iseg, 'icalc'] = self.icalc # in order to initialize a new row
                ireach = 1
                
                # While there is one and only one upstream cell:
                while len(self.upstream_cells_by_ij[ij_outlet]) == 1:
                    self.reach_data.loc[
                        self.reach_data.loc[self.reach_data['iseg'] == 0].index[0], 
                        ['i', 'j', 'iseg', 'ireach']] = [ij_outlet[0],
                                                         ij_outlet[1],
                                                         last_iseg,
                                                         ireach]
                    ij_outlet = self.upstream_cells_by_ij[ij_outlet][0]
                    ireach += 1
                    
                # if there are several upstream cells
                if len(self.upstream_cells_by_ij[ij_outlet]) > 1:
                    self.reach_data.loc[
                        self.reach_data.loc[self.reach_data['iseg'] == 0].index[0], 
                        ['i', 'j', 'iseg', 'ireach']] = [ij_outlet[0],
                                                         ij_outlet[1],
                                                         last_iseg,
                                                         ireach]
                    downstream_iseg = last_iseg
                    for ij_tributary in self.upstream_cells_by_ij[ij_outlet]:
                        last_iseg += 1
                        self.segment_data_1.loc[last_iseg, 'outseg'] = downstream_iseg
                        last_iseg = stream_reconstruct(ij_tributary, last_iseg)
                    return last_iseg
                
                # if there is no upstream cell:
                else:
                    self.reach_data.loc[
                        self.reach_data.loc[self.reach_data['iseg'] == 0].index[0], 
                        ['i', 'j', 'iseg', 'ireach']] = [ij_outlet[0],
                                                         ij_outlet[1],
                                                         last_iseg,
                                                         ireach]
                    return last_iseg
            
    
            # 4. Call the recursive method:   
            last_iseg = 1
            for ij_outlet in outlets:
                last_iseg = stream_reconstruct(ij_outlet, last_iseg) + 1
            
            # Note: if self.segment_data_1 contains nan, Modflow crashes
            self.segment_data_1 = self.segment_data_1.fillna(0)
            self.reach_data.fillna(0)
            
            # 5. Reverse segment and reach numbering:
             # reverse 'iseg' in reach_data:
            self.reach_data['iseg'] = self.reach_data['iseg'].max() + 1 - self.reach_data['iseg']
             # reverse 'ireach' in reach_data:
            for iseg in self.segment_data_1.index:
                self.reach_data.loc[self.reach_data['iseg'] == iseg, 'ireach'] \
                    = self.reach_data.loc[self.reach_data['iseg'] == iseg, 'ireach'].max() + 1 \
                        - self.reach_data.loc[self.reach_data['iseg'] == iseg, 'ireach']
             # reverse 'outseg' in segment_data_1:
            outlet_idx = self.segment_data_1[self.segment_data_1['outseg'] == 0].index.copy()
            self.segment_data_1['outseg'] = self.segment_data_1.index.max() + 1 \
                - self.segment_data_1['outseg']
            self.segment_data_1.loc[outlet_idx, 'outseg'] = 0
             # reverse 'nseg' in segment_data_1:
            self.segment_data_1 = self.segment_data_1[::-1]
            self.segment_data_1.index = self.segment_data_1.index[::-1]
             # reverse index in reach_data:
            self.reach_data = self.reach_data[::-1]
            self.reach_data.index = self.reach_data.index[::-1]
            
            # ---- Fill in the parameter values
            self.reach_data['rchlen'] = self.rchlen
            
            self.segment_data_1['thickm1'] = self.thickm
            self.segment_data_1['thickm2'] = self.thickm
            self.segment_data_1['depth1'] = self.depth
            self.segment_data_1['depth2'] = self.depth
            self.segment_data_1['hcond1'] = self.hcond_max
            self.segment_data_1['hcond2'] = self.hcond_max
            self.segment_data_1['width1'] = self.width
            self.segment_data_1['width2'] = self.width
            
            for idx, r in self.reach_data.iterrows(): # strtop
                self.reach_data.loc[idx, 'strtop'] = self.dem[r['i'], r['j']]
                                                   # self.dem[r['i'], r['j']] - depth
                                                   # self.bottom_layer[r['i'], r['j']]
            
            self.cond_drain = self.hcond_max * self.rchlen * self.width / self.thickm # hcond * self.resolution** 2
            
    
    #%% SET PARAMETERS FOR CRITICAL AREA COMPUTATION
    def critical_cells(self, hcond:float=0.012, area:str='sinks', 
                               sink_threshold:float=0):
        
        self.hcond_min = hcond
        self.critical_mode = area
        self.sink_threshold = sink_threshold
    
    
    #%% CORRECT CONDUCTANCE ON CELLS CRITICAL FOR CONVERGENCE
    def correct_critical_cells(self, geographic):
        
        if self.critical_mode == "sinks":          
            self.crit_area, _, _, nodata = toolbox.load_to_numpy(
                geographic.depressions, 
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem, 
                dst_crs = geographic.crs_proj)
            # self.crit_area[self.crit_area == nodata] = 0
            self.crit_area = np.ma.array(
                self.crit_area, 
                mask = self.crit_area == nodata, 
                fill_value = nodata)
            
            acc_map, _, _, nodata = toolbox.load_to_numpy(
                os.path.join(geographic.reg_path, 'region_acc.tif'), 
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem, 
                dst_crs = geographic.crs_proj)
            
            for dep_val in np.unique(self.crit_area):
                self.crit_area[self.crit_area == dep_val] = acc_map[self.crit_area == dep_val].sum()
            
            # For each segment...
            for nseg, s in self.segment_data_1.iterrows():
                # ... get the corresponding reaches
                r = self.reach_data[self.reach_data['iseg'] == nseg]
                # If this segment is made only of one reach:
                if len(r) == 1:
                    # If this cell is not masked:
                    if not np.ma.is_masked(self.crit_area[r['i'], r['j']]):
                        # If this reach is located on a sink cell:
                        if self.crit_area[r['i'], r['j']] >= self.sink_threshold:
                            # then the upstream and downstream conductivities are set to 0
                            self.segment_data_1.loc[nseg, 'hcond1'] = self.hcond_min
                            self.segment_data_1.loc[nseg, 'hcond2'] = self.hcond_min
                # If this segment is made of two reaches:
                elif len(r) == 2:
                    # If this cell is not masked:
                    if not np.ma.is_masked(self.crit_area[r['i'].iloc[1], r['j'].iloc[1]]):
                        # If the downstream reach is located on a sink cell:
                        if self.crit_area[r['i'].iloc[1], r['j'].iloc[1]] >= self.sink_threshold:
                            # its conductivity is set to 0
                            self.segment_data_1.loc[nseg, 'hcond2'] = self.hcond_min
                    # Same for the upstream reach
                    # If this cell is not masked:
                    if not np.ma.is_masked(self.crit_area[r['i'].iloc[0], r['j'].iloc[0]]):
                        if self.crit_area[r['i'].iloc[0], r['j'].iloc[0]] >= self.sink_threshold:
                            self.segment_data_1.loc[nseg, 'hcond1'] = self.hcond_min
                # For segments made of more than 2 reaches, the segment's conductivity
                # is let as it is.

        elif os.path.isfile(self.critical_mode):
            self.crit_area, _, _, nodata = toolbox.load_to_numpy(
                self.critical_mode,
                src_crs = geographic.crs_proj, 
                base_path = geographic.watershed_dem,
                dst_crs = geographic.crs_proj)
            
    # Adaptation of hcond values to accumulation_flux values
    # =============================================================================
    #         acc_map, _, _, nodata = toolbox.load_to_numpy(
    #             os.path.join(geographic.reg_path, 'region_acc.tif'), 
    #             src_crs = geographic.crs_proj, 
    #             base_path = geographic.watershed_dem, 
    #             dst_crs = geographic.crs_proj)
    #         acc_map = np.ma.array(acc_map, 
    #                               mask = watershed_mask==nodata, 
    #                               fill_value = nodata)
    #         # Threshold version
    # # =============================================================================
    # #         # For each segment...
    # #         for nseg, s in self.segment_data_1.iterrows():
    # #             r = self.reach_data[self.reach_data['iseg'] == nseg]
    # #             # for the upstream reach:
    # #             acc1 = acc_map[r['i'].iloc[0], r['j'].iloc[0]]
    # #             if acc1 > 7.5:
    # #                 self.segment_data_1.loc[nseg, 'hcond1'] = hcond_low
    # #             # for the downstream reach:
    # #             acc2 = acc_map[r['i'].iloc[-1], r['j'].iloc[-1]]
    # #             if acc2 > 7.5:
    # #                 self.segment_data_1.loc[nseg, 'hcond2'] = hcond_low
    # # =============================================================================
    #         
    #         # Linear version
    # # =============================================================================
    # #         # For each segment...
    # #         for nseg, s in self.segment_data_1.iterrows():
    # #             r = self.reach_data[self.reach_data['iseg'] == nseg]
    # #             # for the upstream reach:
    # #             acc1 = max(7.5, acc_map[r['i'].iloc[0], r['j'].iloc[0]])
    # #             self.segment_data_1.loc[nseg, 'hcond1'] = hcond + (hcond_low-hcond)*(acc1-7.5)/(acc_map.max()-7.5)
    # #             # for the downstream reach:
    # #             acc2 = max(7.5, acc_map[r['i'].iloc[-1], r['j'].iloc[-1]])
    # #             self.segment_data_1.loc[nseg, 'hcond2'] = hcond + (hcond_low-hcond)*(acc2-7.5)/(acc_map.max()-7.5)
    # # =============================================================================
    # 
    #         # Logarithmic version
    # # =============================================================================
    # #         # For each segment...
    # #         for nseg, s in self.segment_data_1.iterrows():
    # #             r = self.reach_data[self.reach_data['iseg'] == nseg]
    # #             # for the upstream reach:
    # #             acc1 = max(7.5, acc_map[r['i'].iloc[0], r['j'].iloc[0]])
    # #             self.segment_data_1.loc[nseg, 'hcond1'] = ...
    # #             # for the downstream reach:
    # #             acc2 = max(7.5, acc_map[r['i'].iloc[-1], r['j'].iloc[-1]])
    # #             self.segment_data_1.loc[nseg, 'hcond2'] = ...
    # # =============================================================================
    # =============================================================================
            
    #%% OTHER CORRECTIONS AND DATA IMPROVMENT
    
    def remove_multiple_reaches(self):
        for cell in np.unique(self.reach_data[['i', 'j']]):
            while len(self.reach_data[self.reach_data[['i', 'j']] == cell]) > 1:
                iseg = self.reach_data[self.reach_data[['i', 'j']] == cell]['iseg'].min()
                self.reach_data = self.reach_data[
                    (self.reach_data['i'] != cell[0]) | (self.reach_data['j'] != cell[1]) | (self.reach_data['iseg'] != iseg)
                    ]
                print(f"row {cell[0]}, {cell[1]}, {iseg} removed")
                # iseg = set(self.reach_data[self.reach_data[['i', 'j']] == cell]['iseg']) \
                #     - set([self.reach_data[self.reach_data[['i', 'j']] == cell]['iseg'].max()])
        
    def correct_elevations(self, dem):
        # Correct inconsistent elevations and too small slopes in reach_data 
        # (not reflected on the dem map)
          # Note:
          # It could have been possible to use the <watershed_(box_)buff_fill> DEM
          # as the basis for streambed elevations, or even to use it directly
          # as the self.dem instead of <watershed_(box_)buff_dem>. It yields basically
          # the same results as the current method, except that it is slightly
          # less accurate and can lead to minor "model top violations" (the 
          # strtop is slightly above the surface)
        
        # 1. Correct elevations and effective slopes amongst one segment
        min_slope = 0.001
        min_depression = self.resolution * min_slope
        for nseg, s in self.segment_data_1.iterrows():
            prev_strtop = self.reach_data.loc[self.reach_data[self.reach_data['iseg'] == nseg].index[0], 'strtop'].item()
            
            for r_idx, _ in self.reach_data[self.reach_data['iseg'] == nseg].iterrows():
                self.reach_data.loc[r_idx, 'strtop'] = min(self.reach_data.loc[r_idx, 'strtop'], prev_strtop)
                prev_strtop = self.reach_data.loc[r_idx, 'strtop'] - min_depression
                
            # Correct elevations amongst connected segments
            if s['outseg'] != 0:
                self.reach_data.loc[self.reach_data[self.reach_data['iseg'] == s['outseg']].index[0], 'strtop'] \
                    = min(self.reach_data.loc[self.reach_data[self.reach_data['iseg'] == s['outseg']].index[0], 'strtop'], prev_strtop)
                
        # 2. Update elevdn and elevup in segment_data_1:
        for nseg, _ in self.segment_data_1.iterrows():
            self.segment_data_1.loc[nseg, 'elevdn'] = self.reach_data.loc[self.reach_data['iseg'] == nseg, 'strtop'].min()
            self.segment_data_1.loc[nseg, 'elevup'] = self.reach_data.loc[self.reach_data['iseg'] == nseg, 'strtop'].max()
            if self.segment_data_1.loc[nseg, 'elevdn'] == self.segment_data_1.loc[nseg, 'elevup']:
                self.segment_data_1.loc[nseg, 'elevdn'] = self.segment_data_1.loc[nseg, 'elevdn'] - min_depression/2

        # 3. Reflect these changes on the dem used for the modeling (model_modflow.dem)
# =============================================================================
#         if self.apply_elevations == True:
#             dem[watershed_mask!=nodata] = elev_map[watershed_mask!=nodata]
# =============================================================================

        return dem
    

    #%% DISPLAY PLOT
    
    def display_data(self, etc):
        fontprop = toolbox.plot_params(15,15,18,20)
        
#%% NOTES
