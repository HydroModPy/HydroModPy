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


class Recharge(Process):

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
                 name: str = 'rech',
                 output_name = 'rch'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default simulation: constant, homogeneous recharge 
        self.set_iptpar(genmtd_sdis = 'homogeneous',
                        genmtd_tdis = 'constant',
                        value       = 1e-3,
                        lenuni      = 'm',
                        itmuni      = 'd') 
        
        # default option for spatial & temporal discretization
        self.set_iptpar(sgrid = 'from_shrenv',
                        tgrid = 'from_shrenv')
        # default name for spatial & temporal discretization in shared 
        # environment
        self.set_shrpar(sgrid = 'sdis',
                        tgrid = 'tdis')
        # Default parameters for loading csv files (optional)
        self.set_iptpar(dateheader_chron = 'date',
                        dateformat_chron = '%Y-%m-%d %H:%M:%S',
                        colsep_chron     = '\t',
                        xheader_map_pos  = 'X',
                        yheader_map_pos  = 'Y',
                        idheader_map_pos = 'id',
                        crs_map_pos      = None,
                        colsep_map_pos   = '\t') 
        # Default parameters for reprojecting local spatial & temporal grids
        # into master spatial & temporal grids
        self.set_iptpar(reprojection_tdis = 'closest_neighbor',
                        reprojection_sdis = 'closest_neighbor')
        
        
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
            
        # recharge chronicles (optional)
        genmtd = self.get_iptpar['genmtd_tdis']
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
        
        # location of weather stations (optional)
        genmtd = self.get_iptpar['genmtd_sdis']
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
        # dictionary of recharge map (one for each time period)
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
        genmtd = self.get_iptpar['genmtd_tdis']
        if genmtd == 'constant':
            dateheader = self.get_iptpar['dateheader_chron']
            value      = self.get_iptpar['value']
            tdata = pd.DataFrame(index = [start_datetime], data = {'value':[value]})
            tdata.index.names = [dateheader]
        elif genmtd == 'chronicles_csv' or genmtd == 'chronicles_csv_shrenv':
            tdata = self.get_csdpar['tdata']
        # reprojection of data chronicles to master time discretization
        reprojection = self.get_iptpar['reprojection_tdis']
        if reprojection == 'closest_neighbor':
            matches  = tdata.index.get_indexer(masterdl,method='nearest')
            tdatarep = tdata.iloc[matches]
            tdatarep.index = masterdl
        # Optional: first value for each station is the mean of the
        # whole chronicle for this station
        first_clim = self.get_iptpar.get('first_clim')
        if first_clim == 'mean':
            for station in list(tdatarep):
                tdatarep[station][0] = np.mean(tdata[station]) 
        # save reprojected data chronicles into consolidated parameters
        self._set_csdpar(tdatarep = tdatarep)
           
    def _sdis_generation(self):
        """
        WIP - Description
        """
        # matrix generation
        genmtd_sdis = self.get_iptpar['genmtd_sdis']
        if   genmtd_sdis == 'homogeneous':
            resdict = self._gendict_homogeneous()          
        elif genmtd_sdis == 'map_csv' or genmtd_sdis == 'map_csv_shrenv':
            resdict = self._gendict_map_csv()
        return resdict
    
    
    def _gendict_homogeneous(self):
        """
        WIP - Description
        """
        # master spatial discretization
        sgrid  = self.get_csdpar['sgrid']
        # data chronicles repojected to master time discretization
        mappar = self.get_csdpar['tdatarep']
        idval  = self.get_iptpar.get('idheader_value')
        if idval is None:
            idval  = list(mappar)[0]

        resdict = {}
        for i in list(range(len(mappar.index.values))):
            # 2D matrix (nrow,ncol) for mf5
            resmat = sgrid.top * 0 + mappar[idval][i] 
            # matrix unit conversion into master discretization unit
            resmat = self._unit_conversion(resmat)
            resdict.update({i:resmat})
        return resdict
    
     
    def _gendict_map_csv(self):
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
        # companion parameter csv-file to geological map
        mappar   = self.get_csdpar['tdatarep']
        # === FORMATING
        # formate station map coordinates as npoints-by-2 (2D map) list 
        # of coordinates 
        mapcoord = mappos[[xheader,yheader]].to_numpy()
        # station map crs reprojection to master crs (if necessary)
        if crs_map != sgrid.crs.srs: 
            print('Warning: Station map CRS does not match model grid CRS. \
                  Consider pre-processing CRS reprojection of station map \
                  to improve performances.')
        mapcoord[:,0], mapcoord[:,1]= crs_reprojection(xini    = mapcoord[:,0],
                                                       yini    = mapcoord[:,1],
                                                       crs_in  = crs_map,
                                                       crs_out = sgrid.crs.srs)
        # formate spatial grid cell coordinates as ncells-by-6 list of 
        # coordinates (layer,row,column,x,y,z)
        # @TB: layer, row, column numbers necessary only for mf5 and regular grids
        gridcoord = self.getlist_lrcxyzcellcenters(sgrid)
        # === PROCESSING
        # reprojection of geological model into master spatial discretization
        reprojection_sdis = self.get_iptpar['reprojection_sdis']
        if reprojection_sdis == 'closest_neighbor':
            # for each cell of the model (ncells total), find the closest 
            # neighbor in the geological model (=  shortest euclidian distance)
            dist,points = closest_neighbors(mapcoord,gridcoord[['x','y']].to_numpy(),1)
            id_col = mappos[idheader].iloc[points].to_numpy()
            gridcoord[idheader]=id_col.astype(str)
            # replace facies id by its value given in companion csv-file
            mappar = mappar.transpose()
            mappar = mappar.set_index(mappar.index.astype(str))
            gridcoord=gridcoord.join(mappar,on=idheader) 
            
            
        # === FORMATE AND EXPORT RESULTS
        resdict = {}
        i=0
        for date in list(mappar):
            resmat = sgrid.top * 0
            resmat[gridcoord['r'],gridcoord['c']] = gridcoord[date]  
            # matrix unit conversion into master discretization unit
            resmat     = self._unit_conversion(resmat)
            resdict.update({i:resmat})
            i = i+1
            
        return resdict
    
    
    # matrix unit conversion into master discretization unit
    def _unit_conversion(self,resmat):
        grid_unit  = self.get_csdpar['sgrid'].lenuni
        mat_unit   = self.get_iptpar['lenuni']
        resmat     = unitconversion_length(resmat,mat_unit,grid_unit) 
        grid_unit  = self.get_csdpar['tgrid'].time_units
        mat_unit   = self.get_iptpar['itmuni']
        resmat     = unitconversion_time(resmat,mat_unit,grid_unit,-1)
        return resmat
    
    
    def getlist_lrcxyzcellcenters(self,strgrid):
        xyzccenters = strgrid.xyzcellcenters
        
        Cmatrix = np.arange(len(xyzccenters[0][0,:]))
        Cmatrix = np.repeat(Cmatrix[np.newaxis,...],len(xyzccenters[0][:,0]),axis=0)
        Cmatrix = np.repeat(Cmatrix[np.newaxis,...], len(xyzccenters[2]), axis=0)
        Carray  = Cmatrix.flatten()
        
        Rmatrix = np.arange(len(xyzccenters[1][:,0]))
        Rmatrix = np.repeat(Rmatrix[...,np.newaxis],len(xyzccenters[1][0,:]),axis=1)
        Rmatrix = np.repeat(Rmatrix[np.newaxis,...], len(xyzccenters[2]), axis=0)
        Rarray  = Rmatrix.flatten()
        
        Lmatrix = np.arange(len(xyzccenters[2]))
        Lmatrix = np.repeat(Lmatrix[...,np.newaxis],len(xyzccenters[0][:,0]),axis=1)
        Lmatrix = np.repeat(Lmatrix[...,np.newaxis],len(xyzccenters[1][0,:]),axis=2)
        Larray  = Lmatrix.flatten()        
        
        Xmatrix = xyzccenters[0]
        Xmatrix = np.repeat(Xmatrix[np.newaxis,...], len(xyzccenters[2]), axis=0)
        Xarray  = Xmatrix.flatten()
        
        Ymatrix = xyzccenters[1]
        Ymatrix = np.repeat(Ymatrix[np.newaxis,...], len(xyzccenters[2]), axis=0)
        Yarray  = Ymatrix.flatten()
        
        Zarray  = xyzccenters[2].flatten()
        
        lrcxyzlist = pd.DataFrame({'l': Larray,
                                   'r': Rarray,
                                   'c': Carray,
                                   'x': Xarray,
                                   'y': Yarray,
                                   'z': Zarray})
        
        return lrcxyzlist     
      

# %% NOTES
# TODO@TB: descriptions