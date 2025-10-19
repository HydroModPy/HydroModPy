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


# %% CLASS


class SeaLevel(Process):

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
                 name: str = 'sealvl',
                 output_name: str = 'chd'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default simulation: constant sea level at 0 elevation
        self.set_iptpar(genmtd_tdis = 'constant',
                        value       = 0,
                        lenuni      = 'm') 
        
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
                        colsep_chron     = '\t') 
        # Default parameters for reprojecting local spatial & temporal grids
        # into master spatial & temporal grids
        self.set_iptpar(reprojection_tdis = 'closest_neighbor')
        
        
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
            
        self._isPreprocessed = True
        
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # dictionary of sea level map (one for each time period)
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
        # save reprojected data chronicles into consolidated parameters
        self._set_csdpar(tdatarep = tdatarep)
           
    def _sdis_generation(self):
        """
        WIP - Description
        """
        # === PARAMETER EXTRACTION
        # master spatial discretization
        sgrid  = self.get_csdpar['sgrid']
        dem    = sgrid.top
        # data chronicles reprojected to master time discretization
        mappar = self.get_csdpar['tdatarep']
        idval  = self.get_iptpar.get('idheader_value')
        if idval is None:
            idval  = list(mappar)[0]
        # === FORMATING
        # Convert sea level unit (if necessary)
        mappar[idval] = self._unit_conversion(mappar[idval].to_numpy())
        # formate spatial grid cell coordinates as ncells-by-6 list 
        # (layer,row,column,dem,starting_head,ending_head)
        # @TB: layer, row, column numbers necessary only for mf5 and regular grids
        Cmatrix = np.arange(sgrid.ncol)
        Cmatrix = np.repeat(Cmatrix[np.newaxis,...],sgrid.nrow,axis=0)
        Rmatrix = np.arange(sgrid.nrow)
        Rmatrix = np.repeat(Rmatrix[...,np.newaxis],sgrid.ncol,axis=1)
        Lmatrix = Rmatrix*0
        dem_mat = pd.DataFrame({'l'    : Lmatrix.flatten(),
                                'r'    : Rmatrix.flatten(),
                                'c'    : Cmatrix.flatten(),
                                'dem'  : dem.flatten(),
                                'shead': Lmatrix.flatten()*0,
                                'ehead': Lmatrix.flatten()*0})
        # === PROCESSING
        resdict = {}
        # For each time period; Constant head will be imposed only to top layer
        for i in list(range(len(mappar.index.values))):
            dem_matc = dem_mat.copy()
            dem_matc['shead'] = dem_matc['shead']*0 + mappar[idval][i]
            dem_matc['ehead'] = dem_matc['shead']
            dem_matc = dem_matc[dem_matc['dem'] - dem_matc['shead'] <= 0]
            resmat = dem_matc[['l','r','c','shead','ehead']].to_numpy()
            resdict.update({i:resmat})
            
        return resdict   
        
    
    # matrix unit conversion into master discretization unit
    def _unit_conversion(self,resmat):
        grid_unit  = self.get_csdpar['sgrid'].lenuni
        mat_unit   = self.get_iptpar['lenuni']
        resmat     = unitconversion_length(resmat,mat_unit,grid_unit) 
        return resmat
    

# %% NOTES
# TODO@TB: descriptions