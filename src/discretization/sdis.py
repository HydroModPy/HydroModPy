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

#%% LIBRAIRIES

# Python
import numpy as np
import rasterio
# Flopy
from flopy.discretization import StructuredGrid
# from flopy.discretization import StructuredGrid, UnstructuredGrid, VertexGrid
# Hydromodpy
from tools import Process


#%% CLASS

class SDis(Process):
    """
    WIP
    """
    
    def __init__(self, 
                 name: str = 'sdis',
                 output_name = 'sdis'):
        """
        WIP
        
        Parameters
        ----------
        out_path : str
            Path of the HydroModPy outputs. 
        """
        super().__init__(name, output_name)
        
        # Default coordinate reference system & grid length unit
        # TODO@TB only m implemented as possible unit for grid for now (due to
        # constraints of possible units from flopy Grid class)
        self.set_iptpar(crs    = None, 
                        lenuni = 'm') 
        # Default path for DEM
        self.set_iptpar(genmtd_surf = 'from_demtif_shrenv')
        self.set_shrpar(demtif_path = 'watershed_box_buff_dem')
    
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv: dict = {}):
        """
        Extract and store input data from files / shared environment.
        """
        # Load DEM
        # @TB: WARNING: DEM crs and length units must be the same as indicated
        # in iptpar['crs'] and iptpar['lenuni'] - no in-code check yet
        genmtd_surf = self.get_iptpar['genmtd_surf']
        if genmtd_surf == 'from_demtif':
            tifpath = self.get_iptpar['demtif_path']
            dem  = rasterio.open(tifpath)
            self._set_csdpar(dem = dem)
        elif genmtd_surf == 'from_demtif_shrenv':
            tifpathnam = self.get_shrpar['demtif_path']
            tifpath = self.get_envar(shrenv,tifpathnam)
            dem  = rasterio.open(tifpath)
            self._set_csdpar(dem = dem)
            
        self._isPreprocessed = True
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # structured grid generation
        output = self._strgrid_generation()
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
        
    
    #%%% GRID GENERATION     
    def _strgrid_generation(self):
        # longitudinal & latitudinal discretization 
        delc,delr,surf,xoff,yoff,nrow,ncol = self._hdis()
        # vertical discretization
        botm,nlay = self._vdis(surf)
        # reference coordinate reference system and length unit
        crs    = self.get_iptpar['crs']
        lenuni = self.get_iptpar['lenuni']
        # formating and storage as StructuredGrid class from flopy
        strgrid = StructuredGrid(delc = delc,
                                 delr = delr,
                                 top  = surf,
                                 botm = botm,
                                 xoff = xoff,
                                 yoff = yoff,
                                 nlay = nlay,
                                 nrow = nrow,
                                 ncol = ncol,
                                 crs  = crs,
                                 lenuni = lenuni) 
        return strgrid
    
    #%%%% HORIZONTAL DISCRETIZATION
    def _hdis(self):
        genmtd = self.get_iptpar['genmtd_surf']
        if genmtd == 'from_demtif' or genmtd == 'from_demtif_shrenv':
            delc,delr,surf,xoff,yoff,nrow,ncol = self._hdis_fromtif()
        return delc,delr,surf,xoff,yoff,nrow,ncol
    

    def _hdis_fromtif(self):
        dem  = self.get_csdpar['dem'] 
        nrow = dem.height
        ncol = dem.width
        delc = np.array([dem.transform[0]]*nrow)
        delr = np.array([-dem.transform[4]]*ncol)
        surf = dem.read(1)
        xoff = dem.bounds.left
        yoff = dem.bounds.bottom
        return delc,delr,surf,xoff,yoff,nrow,ncol
    
    #%%%% VERTICAL DISCRETIZATION     
    def _vdis(self,surf):
        genmtd = self.get_iptpar['genmtd_vert']
        if genmtd == 'homogeneous':
            botm,nlay = self._vdis_homogeneous(surf)
        return botm,nlay
 
   
    def _vdis_homogeneous(self,surf):
        nlay   = self.get_iptpar['nlay']
        lthick = self.get_iptpar['lay_thickness']
        
        if not isinstance(lthick,list): 
            lthick = [lthick] * nlay
        cthick = np.cumsum(lthick)
        botm = np.zeros((nlay,len(surf[:,0]),len(surf[0,:])))
        for i in range(len(cthick)):
            botm[i,:,:] = surf - cthick[i]
        return botm,nlay
    
    
#%% NOTES
# TODO@TB: DEM crs and length unit should be checked and reprojected if necessary