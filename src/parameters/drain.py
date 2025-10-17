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


class Drain(Process):

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
                 name: str = 'drain',
                 output_name: str = 'drn'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default simulation: drains at surface level at all cells except where
        # constant head boundary conditions are present. Drain conductance for 
        # each celle will be calculated as C = (K*res_x*res_y)/thickness, where
        # K is the hydraulic conductivity, res_x and res_y are the cell 
        # dimensions in the x and y direction, and thickness is the vertical
        # thickness of the draining layer
        self.set_iptpar(genmtd_sdis  = 'surface_no_constanthead',
                        genmtd_value = 'conductance',
                        thickness    = 1,
                        lenuni       = 'm') 
        
        # default option for spatial & temporal discretization
        self.set_iptpar(sgrid = 'from_shrenv',
                        tgrid = 'from_shrenv')
        # default option for constant head data: ibound (initial constant head)
        # and chd (time-vraiable constant head, e.g. sea level). No drain will
        # be set where constant head boundary conditions are present
        self.set_iptpar(ibound = 'from_shrenv',
                        chd    = 'from_shrenv')
        # default option for hydraulic conductivity
        self.set_iptpar(hk = 'from_shrenv')
        
        # default names for variables in shared environment
        self.set_shrpar(sgrid  = 'sdis',
                        tgrid  = 'tdis',
                        ibound = 'ibound',
                        chd    = 'chd',
                        hk     = 'hk')
        
        
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
            
        # constant heads and hydraulic conductivity from shared environment
        if self._iptpar['ibound'] == 'from_shrenv':
            iboundnam = self.get_shrpar['ibound']
            ibound = self.get_envar(shrenv,iboundnam)
            self._set_csdpar(ibound = ibound)
        if self._iptpar['chd'] == 'from_shrenv':
            chdnam = self.get_shrpar['chd']
            chd = self.get_envar(shrenv,chdnam)
            self._set_csdpar(chd = chd)
        if self._iptpar['hk'] == 'from_shrenv':
            hknam = self.get_shrpar['hk']
            hk = self.get_envar(shrenv,hknam)
            self._set_csdpar(hk = hk)
            
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
        # === PARAMETER EXTRACTION
        # master discretization: dem, horizontal and vertical resolution
        sgrid  = self.get_csdpar['sgrid']
        dem    = sgrid.top
        delr   = sgrid.delr
        delc   = sgrid.delc
        tgrid  = self.get_csdpar['tgrid']
        # Hydraulic conductivity: only top layer 
        hk     = self.get_csdpar['hk']
        hk     = hk[0,:,:]
        # initial and time variable heads
        ibound = self.get_csdpar['ibound']
        chd    = self.get_csdpar['chd']
        # Drain layer thickness
        thick  = self.get_iptpar['thickness']
        thick  = self._unit_conversion(thick) # Unit conversion (if necessary)
        # formate spatial grid cell coordinates and parameters
        # @TB: layer, row, column numbers necessary only for mf5 and regular grids
        Cmatrix = np.arange(sgrid.ncol)
        Cmatrix = np.repeat(Cmatrix[np.newaxis,...],sgrid.nrow,axis=0)
        Rmatrix = np.arange(sgrid.nrow)
        Rmatrix = np.repeat(Rmatrix[...,np.newaxis],sgrid.ncol,axis=1)
        Lmatrix = Rmatrix*0
        resxmat = np.repeat(delr[np.newaxis,...],sgrid.nrow,axis=0)
        resymat = np.repeat(delc[...,np.newaxis],sgrid.ncol,axis=1)
        thicmat = Rmatrix*0 + thick
        parmat  = pd.DataFrame({'l'    : Lmatrix.flatten(),
                                'r'    : Rmatrix.flatten(),
                                'c'    : Cmatrix.flatten(),
                                'dem'  : dem.flatten(),
                                'hk'   : hk.flatten(),
                                'resx' : resxmat.flatten(),
                                'resy' : resymat.flatten(),
                                'thick': thicmat.flatten()})
        # ibound  = ibound[0,:,:]
        # ibound  = ibound.flatten()
        # === PROCESSING
        # conductance for each cell drain C = K*resy*resx/thick
        cond = np.multiply(parmat['hk'],parmat['resx'])
        cond = np.multiply(cond,parmat['resy'])
        cond = np.divide(cond,parmat['thick'])
        parmat['cond'] = cond
        resdict = {}
        # For each time period; Constant head will be imposed only to top layer
        for i in list(range(len(tgrid.perlen))):
            matc = parmat.copy()
            if chd != None:
                chdc = chd[i]
                # once a cell is flagged as constant head, remains constant head
                # until the end of simulation even if not flagged as such in
                # subsequent time periods
                ibound[chdc[:,0].astype(int),chdc[:,1].astype(int),chdc[:,2].astype(int)] = -1
            iboundtemp = ibound[0,:,:]
            iboundtemp = iboundtemp.flatten()
            # no drain where ibound != 1
            matc.drop(matc[iboundtemp != 1].index, inplace=True)
            # formate exports
            resmat = matc[['l','r','c','dem','cond']].to_numpy()
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