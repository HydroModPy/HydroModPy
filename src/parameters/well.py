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
from tools.toolbox import closest_neighbors


# %% CLASS


class Well(Process):

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
                 name: str = 'well',
                 output_name: str = 'wel'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default simulation: constant, homogeneous recharge 
        self.set_iptpar(genmtd_pos        = 'map_csv',
                        genmtd_total_flux = 'chronicles_csv',
                        genmtd_zdstr_flux = 'proportional_transmissivity',
                        opposite_flux_sign_option
                                          = False,
                        lenuni            = 'm',
                        itmuni            = 'd') 
        
        # default option for spatial & temporal discretization
        self.set_iptpar(sgrid = 'from_shrenv',
                        tgrid = 'from_shrenv')
        # default option for hydraulic conductivity (used to calculate T)
        self.set_iptpar(hk = 'from_shrenv')
        
        # default name for spatial & temporal discretization, and hydraulic 
        # conductivity in shared environment
        self.set_shrpar(sgrid = 'sdis',
                        tgrid = 'tdis',
                        hk    = 'hk')
        # Default parameters for loading csv files (optional)
        self.set_iptpar(dateheader_chron = 'date',
                        dateformat_chron = '%Y-%m-%d %H:%M:%S',
                        colsep_chron     = '\t',
                        xheader_map_pos  = 'X',
                        yheader_map_pos  = 'Y',
                        dbotheader_map_pos  = 'dbot',
                        dtopheader_map_pos  = 'dtop',
                        idheader_map_pos = 'id',
                        crs_map_pos      = None,
                        colsep_map_pos   = '\t') 
        # Default parameters for reprojecting temporal grid into master 
        # temporal grid
        self.set_iptpar(reprojection_tdis = 'closest_neighbor_before')
        
        
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv):
        """
        Extract and store input data from files / shared environment.
        """
        # master spatial & time discretization from shared environment
        if self._iptpar['sgrid'] == 'from_shrenv':
            sgridnam = self.get_shrpar['sgrid']
            sgrid = self.get_envar(shrenv,sgridnam)
            self._set_csdpar(sgrid = sgrid)
        if self._iptpar['tgrid'] == 'from_shrenv':
            tgridnam = self.get_shrpar['tgrid']
            tgrid = self.get_envar(shrenv,tgridnam)
            self._set_csdpar(tgrid = tgrid)
            
        # hydraulic conductivity from shared environment
        if self._iptpar['hk'] == 'from_shrenv':
            hknam = self.get_shrpar['hk']
            hk = self.get_envar(shrenv,hknam)
            self._set_csdpar(hk = hk)
            
        # flux chronicles
        genmtd = self.get_iptpar['genmtd_total_flux']
        if genmtd == 'chronicles_csv' or genmtd == 'chronicles_csv_shrenv':
            if genmtd == 'chronicles_csv':
                filepath = self.get_iptpar['fpath_chron']
            if genmtd == 'chronicles_csv_shrenv':
                filenam  = self.get_shrpar['fpath_chron']
                filepath = self.get_envar(shrenv,filenam)
            dateheader   = self.get_iptpar['dateheader_chron']
            dateformat   = self.get_iptpar['dateformat_chron']
            colsep       = self.get_iptpar['colsep_chron']
            
            tdata = pd.read_csv(filepath, sep = colsep, index_col=dateheader)
            tdata.index = pd.to_datetime(tdata.index, format = dateformat) 
            self._set_csdpar(tdata = tdata)
        
        # location of wells
        genmtd = self.get_iptpar['genmtd_pos']
        if genmtd == 'map_csv' or genmtd == 'map_csv_shrenv':
            if genmtd == 'map_csv':
                filepath = self.get_iptpar['fpath_map_pos']
            if genmtd == 'map_csv_shrenv':
                filenam  = self.get_shrpar['fpath_map_pos']
                filepath = self.get_envar(shrenv,filenam)
            colsep       = self.get_iptpar['colsep_map_pos']
            
            mappos = pd.read_csv(filepath, sep = colsep)
            self._set_csdpar(mappos = mappos)
            
        self._isPreprocessed = True
        
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # dictionary of well positions and fluxes (one entry for each time period)
        output = self._dict_generation()   
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
    
    # %%% DICTIONARY GENERATION
    def _dict_generation(self):
        """
        WIP - Description
        """
        # reprojects input data chronicles into master time discretization
        self._tdis_generation()
        # get spatial grid for each time period as a dict
        resdict = self._sdis_generation()
        
        return resdict
    
    def _tdis_generation(self):
        # master time discretization (date array need to be reconstructed from
        # start_datetime and periods lengths)
        tgrid          = self.get_csdpar['tgrid']
        start_datetime = tgrid.start_datetime
        totim          = tgrid.totim
        itmuni         = tgrid.time_units
        masterdl       = pd.to_datetime(totim, unit=itmuni,origin=start_datetime)
        # get (and formate if necessary) input data chronicles
        genmtd = self.get_iptpar['genmtd_total_flux']
        if genmtd == 'chronicles_csv' or genmtd == 'chronicles_csv_shrenv':
            tdata = self.get_csdpar['tdata']
        # reprojection of data chronicles to master time discretization
        reprojection = self.get_iptpar['reprojection_tdis']
        if reprojection == 'closest_neighbor_before':
            matches  = tdata.index.get_indexer(masterdl,method='pad')
        elif reprojection == 'closest_neighbor':
            matches  = tdata.index.get_indexer(masterdl,method='nearest')  
        tdatarep = tdata.iloc[matches]
        tdatarep.index = masterdl
        # unit conversion (if necessary)
        tdatarep.loc[:,:] = self._unit_conversion(tdatarep.values) 
        # flux rates sign conversion to opposite (optional)
        # pumping rates in modflow must be negative (positive rates for 
        # injection wells); this option is to allow keeping positive pumping 
        # rates values in input files 
        opposite_sign_option = self.get_iptpar['opposite_flux_sign_option']
        if opposite_sign_option == True:
            tdatarep.loc[:,:] = tdatarep.values * -1
        # save reprojected data chronicles into consolidated parameters
        self._set_csdpar(tdatarep = tdatarep)
           
    def _sdis_generation(self):
        """
        WIP - Description
        """
        # === PARAMETER EXTRACTION
        # master spatial discretization
        sgrid    = self.get_csdpar['sgrid']
        # geological map csv-file
        mappos   = self.get_csdpar['mappos']
        hkgrid   = self.get_csdpar['hk']
        xheader  = self.get_iptpar['xheader_map_pos']
        yheader  = self.get_iptpar['yheader_map_pos']
        dbheader = self.get_iptpar['dbotheader_map_pos']
        dtheader = self.get_iptpar['dtopheader_map_pos']
        idheader = self.get_iptpar['idheader_map_pos']
        crs_map  = self.get_iptpar['crs_map_pos']
        # companion parameter csv-file to geological map
        mappar   = self.get_csdpar['tdatarep']
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
        # depth matrix
        zmat = sgrid.top_botm
        surf = zmat[0,:,:]
        surfmat = np.repeat(surf[np.newaxis,:, :], len(zmat[:,0,0]), axis=0)
        depthmat = surfmat - zmat
        # === PROCESSING
        # gets the (layer,column,row) location for each well, as well as the 
        # fraction of total water flux pumped/injected in each layer for each
        # well (function of transmissivity)
        wellres = {}
        for well in mappar:
            # get x/y position of wells as model col/row number
            x = mappos[xheader][mappos[idheader]==well].to_numpy()[0]
            c = np.argmin(np.abs(xcenters - x))
            y = mappos[yheader][mappos[idheader]==well].to_numpy()[0]
            r = np.argmin(np.abs(ycenters - y))
            # array of depths at c/r position
            darray = depthmat[:,r,c]
            dtop = mappos[dtheader][mappos[idheader]==well].to_numpy()[0]
            temp = darray - dtop
            temp[temp>0] = np.inf
            ltop = np.argmin(np.abs(temp))
            dbot = mappos[dbheader][mappos[idheader]==well].to_numpy()[0]
            temp = darray - dbot
            temp[temp>=0] = np.inf
            lbot = np.argmin(np.abs(temp))
            # Fraction of flux in each layer
            if lbot == ltop: 
                resmat = [lbot, r, c, 1]
                wellres.update({well: resmat})
                continue
            llist = np.arange(ltop,lbot+1)
            karray = hkgrid[:,r,c]
            resmat = np.zeros((len(llist),4)) 
            genmtd = self.get_iptpar['genmtd_zdstr_flux']
            if genmtd =='proportional_transmissivity':
                for i in list(range(len(llist))):
                    if i == 0:
                        e = darray[ltop+1] - dtop    
                    elif i == len(llist)-1:
                        e = dbot - darray[lbot] 
                    else:
                        e = darray[i+1] - darray[i] 
                    k = karray[i]
                    T = k * e
                    resmat[i,:] = [i, r, c, T]
                resmat[:,3] = resmat[:,3]/np.sum(resmat[:,3])
            wellres.update({well: resmat})
        # For each time period
        resdict = {}
        for i in list(range(len(mappar.index.values))):
            for well in mappar:
                Qtot = mappar[well][i]
                resmati = wellres[well].copy()
                resmati[:,3] = resmati[:,3] * Qtot
                if well == list(mappar)[0]:
                    resmat = resmati
                else:
                    resmat = np.concatenate((resmat,resmati))
            resdict.update({i:resmat})
   
        return resdict
    
    # matrix unit conversion into master discretization unit
    def _unit_conversion(self,resmat):
        grid_unit  = self.get_csdpar['sgrid'].lenuni
        mat_unit   = self.get_iptpar['lenuni']
        resmat     = unitconversion_length(resmat,mat_unit,grid_unit,3) 
        grid_unit  = self.get_csdpar['tgrid'].time_units
        mat_unit   = self.get_iptpar['itmuni']
        resmat     = unitconversion_time(resmat,mat_unit,grid_unit,-1)
        return resmat
    

# %% NOTES
# TODO@TB: descriptions