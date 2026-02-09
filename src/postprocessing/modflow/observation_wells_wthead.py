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

# %% LIBRAIRIES

# Python
import pandas as pd
import numpy as np
# Hydromodpy
from tools import Process
from tools.toolbox import unitconversion_length
from tools.toolbox import unitconversion_time
from tools.toolbox import crs_reprojection
# Flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp


# %% CLASS


class ObservationWellsWTHead(Process):

    """ 
    WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'mfpp_obs_wells',
                 output_name: str = 'mfpp_obs_wells'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # default: well positions from .csv file
        self.set_iptpar(well_pos = 'map_csv') 
        # default: head data from mf simulation results
        self.set_iptpar(wt_head = 'mf_res') 
        
        # default value for dry cell values
        self.set_iptpar(drycellval = -1e30)
        
        # Default parameters for loading csv files (optional)
        self.set_iptpar(xheader_map_pos  = 'X',
                        yheader_map_pos  = 'Y',
                        idheader_map_pos = 'id',
                        crs_map_pos      = None,
                        colsep_map_pos   = '\t') 
        
        # default option for spatial discretization
        self.set_iptpar(sgrid = 'from_shrenv')
        
        # default name for spatial & temporal discretization, and hydraulic 
        # conductivity in shared environment
        self.set_shrpar(sgrid = 'sdis')
        
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv):
        """
        Extract and store input data from files / shared environment.
        """
        # location of wells
        if self._iptpar['well_pos'] == 'map_csv':
            filepath = self.get_iptpar['fpath_wellpos']
            colsep   = self.get_iptpar['colsep_map_pos']
            mappos   = pd.read_csv(filepath, sep = colsep)
            self._set_csdpar(mappos = mappos)
            
        # modflow simulation results: watertable elevation chronicles
        if self._iptpar['wt_head'] == 'mf_res':
            folderpath = self.get_iptpar['folderpath_mfres']
            head_fpu = fpu.HeadFile(folderpath+'.hds')
            self._set_csdpar(head_fpu = head_fpu)
            times = head_fpu.get_times()
            self._set_csdpar(times = times)
        elif self._iptpar['wt_head'] == 'raster_npy':
            filepath = self.get_iptpar['filepath_raster_npy']
            heads = np.load(filepath)
            self._set_csdpar(heads = heads)
        
        # master spatial discretization from shared environment
        if self._iptpar['sgrid'] == 'from_shrenv':
            sgridnam = self.get_shrpar['sgrid']
            sgrid = self.get_envar(shrenv,sgridnam)
            self._set_csdpar(sgrid = sgrid)
            
        # if self._iptpar['tgrid'] == 'from_shrenv':
        #     tgridnam = self.get_shrpar['tgrid']
        #     tgrid = self.get_envar(shrenv,tgridnam)
        #     self._set_csdpar(tgrid = tgrid)

        self._isPreprocessed = True
        
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # dataframe of watertable elevation chronicles at selected observation wells
        output = self._df_generation()   
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
    
    # %%% DICTIONARY GENERATION
    def _df_generation(self):
        """
        WIP - Description
        """
        if self._iptpar['wt_head'] == 'mf_res':
            df = self._df_generation_from_mfres()
        elif self._iptpar['wt_head'] == 'raster_npy':
            df = self._df_generation_from_rasternpy()
            
        return df
    
    def _df_generation_from_rasternpy(self):
        # === PARAMETER EXTRACTION
        # master spatial discretization
        sgrid    = self.get_csdpar['sgrid']
        # geological map csv-file
        mappos   = self.get_csdpar['mappos']
        xheader  = self.get_iptpar['xheader_map_pos']
        yheader  = self.get_iptpar['yheader_map_pos']
        idheader = self.get_iptpar['idheader_map_pos']
        crs_map  = self.get_iptpar['crs_map_pos']
        # 4D matrix of water table elevation results
        heads   = self.get_csdpar['heads']
        # drycellval = self.get_iptpar['drycellval']
        
        # === FORMATING
        # formate station map coordinates as npoints-by-2 (2D map) list 
        # of coordinates 
        mapcoord = mappos[[xheader,yheader]].to_numpy()
        # station map crs reprojection to master crs (if necessary)
        if crs_map != sgrid.crs.srs: 
            print('Warning: well map CRS does not match model grid CRS. \
                  Consider pre-processing CRS reprojection of well map \
                  to improve performances.')
        mapcoord[:,0], mapcoord[:,1]= crs_reprojection(xini    = mapcoord[:,0],
                                                       yini    = mapcoord[:,1],
                                                       crs_in  = crs_map,
                                                       crs_out = sgrid.crs.srs)
        # formate spatial grid cell coordinates
        xyzccenters = sgrid.xyzcellcenters
        xcenters    = xyzccenters[0][0,:]
        ycenters    = xyzccenters[1][:,0]
        # === PROCESSING
        # gets the (column,row) location for each well
        wellrc = mapcoord
        for i in list(range(len(mapcoord[:,0]))):
            well = mappos[idheader][i]
            # get x/y position of wells as model col/row number
            x = mappos[xheader][mappos[idheader]==well].to_numpy()[0]
            c = np.argmin(np.abs(xcenters - x))
            y = mappos[yheader][mappos[idheader]==well].to_numpy()[0]
            r = np.argmin(np.abs(ycenters - y))
            # well positions as row/column
            wellrc[i,0] = r
            wellrc[i,1] = c
            wellrc = wellrc.astype(int)
            
        df = pd.DataFrame()
        df[idheader] = mappos[idheader]
        df.set_index

        val = heads[wellrc[:,0],wellrc[:,1]]
        df[0] = val
        
        # Formate outputs
        df = df.set_index(idheader)
        df = df.transpose()
        
        return df
    
    def _df_generation_from_mfres(self):
        """
        WIP - Description
        """
        # === PARAMETER EXTRACTION
        # master spatial discretization
        sgrid    = self.get_csdpar['sgrid']
        # geological map csv-file
        mappos   = self.get_csdpar['mappos']
        xheader  = self.get_iptpar['xheader_map_pos']
        yheader  = self.get_iptpar['yheader_map_pos']
        idheader = self.get_iptpar['idheader_map_pos']
        crs_map  = self.get_iptpar['crs_map_pos']
        # 4D matrix of water table elevation results
        head_fpu   = self.get_csdpar['head_fpu']
        drycellval = self.get_iptpar['drycellval']
        # simulation times
        times    = self.get_csdpar['times']
        # === FORMATING
        # formate station map coordinates as npoints-by-2 (2D map) list 
        # of coordinates 
        mapcoord = mappos[[xheader,yheader]].to_numpy()
        # station map crs reprojection to master crs (if necessary)
        if crs_map != sgrid.crs.srs: 
            print('Warning: well map CRS does not match model grid CRS. \
                  Consider pre-processing CRS reprojection of well map \
                  to improve performances.')
        mapcoord[:,0], mapcoord[:,1]= crs_reprojection(xini    = mapcoord[:,0],
                                                       yini    = mapcoord[:,1],
                                                       crs_in  = crs_map,
                                                       crs_out = sgrid.crs.srs)
        # formate spatial grid cell coordinates
        xyzccenters = sgrid.xyzcellcenters
        xcenters    = xyzccenters[0][0,:]
        ycenters    = xyzccenters[1][:,0]
        # === PROCESSING
        # gets the (column,row) location for each well
        wellrc = mapcoord
        for i in list(range(len(mapcoord[:,0]))):
            well = mappos[idheader][i]
            # get x/y position of wells as model col/row number
            x = mappos[xheader][mappos[idheader]==well].to_numpy()[0]
            c = np.argmin(np.abs(xcenters - x))
            y = mappos[yheader][mappos[idheader]==well].to_numpy()[0]
            r = np.argmin(np.abs(ycenters - y))
            # well positions as row/column
            wellrc[i,0] = r
            wellrc[i,1] = c
            wellrc = wellrc.astype(int)
            
        # For each time period
        df = pd.DataFrame()
        df[idheader] = mappos[idheader]
        df.set_index
        for item, time in enumerate(times):
            head = head_fpu.get_data(totim=time)  
            if sgrid.nlay == 1:
                head_data = head[0]
            else:
                head_data = pp.get_water_table(head, drycellval)
            val = head_data[wellrc[:,0],wellrc[:,1]]
            df[time] = val
            
        # Formate outputs
        df = df.set_index(idheader)
        df = df.transpose()

        return df        
    

# %% NOTES
# TODO@TB: descriptions