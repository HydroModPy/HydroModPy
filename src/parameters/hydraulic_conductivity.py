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


class HydraulicConductivity(Process):

    """ 
    TODO@TB: Description WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'hhc',
                 output_name: str = 'hk'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default hydraulic conductivity field generation: homogeneous field
        self.set_iptpar(genmtd_sdis = 'homogeneous',
                        value       = 8.6e-1,
                        lenuni      = 'm',
                        itmuni      = 'd')
 
        # Default option & path for master spatial discretization 
        self.set_iptpar(sgrid = 'from_shrenv')
        self.set_shrpar(sgrid = 'sdis')
        
        # Default option & path for master time discretization (used to get master 
        # unit time)
        self.set_iptpar(tgrid = 'from_shrenv')
        self.set_shrpar(tgrid = 'tdis')
        
        # default parameters for using geological model (optional)
        # Geological map csv-file
        self.set_iptpar(xheader_map_pos  = 'X',
                        yheader_map_pos  = 'Y',
                        zheader_map_pos  = 'Z',
                        idheader_map_pos = 'id',
                        crs_map_pos      = None,
                        colsep_map_pos   = '\t')
        # Companion parameter csv-file to geological map
        self.set_iptpar(colsep_map_par = '\t')
        # Default parameters for reprojecting geological model into master 
        # spatial discretization
        self.set_iptpar(reprojection_sdis = 'closest_neighbor')
        
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
            
        # geological map file & companion parametrization file (optional)
        if self.get_iptpar['genmtd_sdis'] == 'map_csv':
            # Geological map csv-file
            mapposfp = self.get_iptpar['fpath_map_pos']
            mapposcs = self.get_iptpar['colsep_map_pos']
            mappos   = pd.read_csv(mapposfp, sep = mapposcs)
            self._set_csdpar(mappos = mappos)
            # Companion parameter csv-file to geological map
            mapparfp = self.get_iptpar['fpath_map_par']
            mapparcs = self.get_iptpar['colsep_map_par'] 
            mappar   = pd.read_csv(mapparfp, sep = mapparcs, index_col=0)
            self._set_csdpar(mappar = mappar)     
            
        self._isPreprocessed = True
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # 3D matrix of hydraulic conductivities
        output = self._matrix_generation()
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
        
    # %%% MATRIX GENERATION    
    def _matrix_generation(self):
        """
        WIP - Description
        """
        # matrix generation
        genmtd_sdis = self.get_iptpar['genmtd_sdis']
        if   genmtd_sdis == 'homogeneous':
            resmat = self._genmat_homogeneous()          
        elif genmtd_sdis == 'exp_decay_depth':
            resmat = self._genmat_exp_decay_depth()   
        elif genmtd_sdis == 'map_csv':
            resmat = self._genmat_map_csv()
        # matrix unit conversion into master discretization unit
        resmat     = self._unit_conversion(resmat)
    
        return resmat
    
    
    def _genmat_homogeneous(self):
        """
        WIP - Description
        """
        val    = self.get_iptpar['value']
        botm   = self.get_csdpar['sgrid'].botm
        
        resmat = botm * 0 + val
        return resmat
        

    def _genmat_exp_decay_depth(self):
        """
        WIP - Description
        """
        topval = self.get_iptpar['surfvalue']
        ddec   = self.get_iptpar['decay_constant']
        minval = self.get_iptpar.get('minvalue')     # Optional
        zmat   = self.get_csdpar['sgrid'].xyzcellcenters[2]
        surf   = self.get_csdpar['sgrid'].top
        
        # depth matrix
        surfmat = np.repeat(surf[np.newaxis,:, :], len(zmat[:,0,0]), axis=0)
        depthmat = surfmat - zmat

        resmat   = topval * np.exp(-ddec * depthmat)
        if minval is not None:
            resmat[resmat<minval] = minval
            
        return resmat
    
     
    def _genmat_map_csv(self):
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
        zheader  = self.get_iptpar.get('zheader_map_pos')
        idheader = self.get_iptpar['idheader_map_pos']
        crs_map  = self.get_iptpar['crs_map_pos']
        # companion parameter csv-file to geological map
        mappar   = self.get_csdpar['mappar']
        idval    = self.get_iptpar.get('idheader_value')
        # === FORMATING
        # formate geological map coordinates as npoints-by-3 (3D map) list 
        # of coordinates (uses default z=0 value in case of 2D map)
        if zheader is None:
            mapcoord      = mappos[[xheader,yheader,yheader]].to_numpy()
            mapcoord[:,2] = 0
        else:
            mapcoord = mappos[[xheader,yheader,zheader]].to_numpy()
        # geological map crs reprojection to master crs (if necessary)
        if crs_map != sgrid.crs.srs: 
            print('Warning: Geological map CRS does not match model grid CRS. \
                  Consider pre-processing CRS reprojection of geological map \
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
            dist,points = closest_neighbors(mapcoord,gridcoord[['x','y','z']].to_numpy(),1)
            id_col = mappos[idheader].iloc[points].to_numpy()
            gridcoord[idheader]=id_col.astype(str)
            # replace facies id by its value given in companion csv-file
            mappar = mappar.transpose()
            mappar = mappar.set_index(mappar.index.astype(str))
            gridcoord=gridcoord.join(mappar,on=idheader)            
        # === FORMATE AND EXPORT RESULTS
        resmat = sgrid.botm * 0 # 3D matrix (nlay,nrow,ncol) for mf5
        if idval == None:
            resmat[gridcoord['l'],gridcoord['r'],gridcoord['c']] = gridcoord.iloc[:,-1]       
        else:
            resmat[gridcoord['l'],gridcoord['r'],gridcoord['c']] = gridcoord[idval]  
        return resmat
    
    
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
# TODO@TB: methods descriptions