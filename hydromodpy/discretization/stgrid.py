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
from flopy.discretization import StructuredGrid, UnstructuredGrid, VertexGrid
from flopy.discretization.modeltime import ModelTime


# %% CLASS

class STGrid:
    """
    Class for a spatio-temporal grid, i.e. a combination of a spatial grid and a temporal grid.
    """
    
    # %%% INITIALIZATION
    # Initialization
    def __init__(self):
        # Default values for spatial and temporal grids
        self._sgrid       = None
        self._tgrid       = None
        # Default parameter for choosing type of spatial grid to create
        self._sgrid_type  = None
        # Default parameters for structured spatial grid creation
        self._top_path        = None
        self._crs             = None
        self._lenuni          = None
        self._bot_path        = None
        self._thick           = None
        self._lay_proportions = None
        self._lay_decay       = None
        self._nlay            = None
        # Initialization of flags for checking if  parameters for spatial or temporal grid 
        # creation have not been modified since last grid creation
        self._sgrid_created = False
        self._tgrid_created = False
        # Default parameters for no data value
        self.nodata = -9999

    # %%% GETTERS FOR SPATIAL AND TEMPORAL GRIDS
    # Getter for spatial grid
    @property
    def sgrid(self):
        if not self._sgrid_created:
            self._create_sgrid()
        return self._sgrid
    
    # Getter for temporal grid
    @property
    def tgrid(self):
        if not self._tgrid_created:
            self._create_tgrid()
        return self._tgrid

    # %%% SETTERS AND GETTERS FOR PARAMETERS FOR SPATIAL GRID CREATION
    # Setter and getter for top_path
    @property
    def top_path(self):
        return self._top_path   
    @top_path.setter
    def top_path(self, value):
        self._top_path = value
        self._sgrid_created = False

    # Setter and getter for crs
    @property
    def crs(self):
        return self._crs
    @crs.setter
    def crs(self, value):
        self._crs = value
        self._sgrid_created = False

    # Setter and getter for lenuni
    @property
    def lenuni(self):
        return self._lenuni
    @lenuni.setter
    def lenuni(self, value):
        self._lenuni = value
        self._sgrid_created = False

    # Setter and getter for lay_decay
    @property
    def lay_decay(self):
        return self._lay_decay
    @lay_decay.setter
    def lay_decay(self, value):
        self._lay_decay = value
        self._sgrid_created = False

    # Setter and getter for bot_path
    @property  
    def bot_path(self):
        return self._bot_path
    @bot_path.setter
    def bot_path(self, value):
        self._bot_path = value
        self._sgrid_created = False

    # Setter and getter for nlay
    @property
    def nlay(self):
        return self._nlay
    @nlay.setter
    def nlay(self, value):
        self._nlay = value
        self._sgrid_created = False

    # Setter and getter for thick
    @property
    def thick(self):
        return self._thick
    @thick.setter
    def thick(self, value):
        self._thick = value
        self._sgrid_created = False

    # Setter and getter for lay_proportions
    @property
    def lay_proportions(self):
        return self._lay_proportions
    @lay_proportions.setter
    def lay_proportions(self, value):
        self._lay_proportions = value
        self._sgrid_created = False

    # %%% SETTERS AND GETTERS FOR PARAMETERS FOR TEMPORAL GRID CREATION

    # %%% SPATIAL GRID CREATION
    # Spatial grid creation according to sgrid_type parameter
    def _create_sgrid(self):
        """
        Create the spatial grid.
        """
        if self._sgrid_type is None:
            print('Error: sgrid_type parameter for spatial grid creation has not been set and is required for spatial grid creation.')
            return
        elif self._sgrid_type == 'structured':
            self._sgrid = self._create_sgrid_structured()
        elif self._sgrid_type == 'unstructured':
            self._sgrid = self._create_sgrid_unstructured()
        elif self._sgrid_type == 'vertex':
            self._sgrid = self._create_sgrid_vertex()
        self._sgrid_created = True
    # %%%% STRUCTURED SPATIAL GRID CREATION
    # Creation methods for structured spatial grid
    def _create_sgrid_structured(self):
        """
        Create a structured spatial grid.
        """
        # longitudinal & latitudinal structured grid
        top,delc,delr,surf,xoff,yoff,nrow,ncol = self._create_hgrid_structured()
        # vertical structured grid
        botm,nlay = self._create_vgrid_structured(top)
        # formating and storage as StructuredGrid class from flopy
        sgrid = StructuredGrid(delc = delc,
                               delr = delr,
                               top  = surf,
                               botm = botm,
                               xoff = xoff,
                               yoff = yoff,
                               nlay = nlay,
                               nrow = nrow,
                               ncol = ncol,
                               crs  = self.crs,
                               lenuni = self.lenuni) 
        return sgrid
    
    # longitudinal & latitudinal structured grid
    def _create_hgrid_structured(self):
        """
        Create the horizontal grid for a structured spatial grid.
        """
        top  = rasterio.open(self.top_path)
        nrow = top.height
        ncol = top.width
        delc = np.array([top.transform[0]]*nrow)
        delr = np.array([-top.transform[4]]*ncol)
        surf = top.read(1)
        xoff = top.bounds.left
        yoff = top.bounds.bottom
        return top,delc,delr,surf,xoff,yoff,nrow,ncol
    
    # vertical structured grid
    def _create_vgrid_structured(self,top):
        """
        Create the vertical grid for a structured spatial grid.
        """
        # Definition of the bottom layer of the domain
        if self.bot_path is None:
            bot = top - self.thick        # Matrix for constant thickness case
            bot[top<=self.nodata]=self.nodata
        else:
            bot = rasterio.open(self.bot_path)
            bot[top<=self.nodata]=self.nodata
        # Parameters for proportions of the thciknesses of all layers as a fraction of total domain thickness
        if self.lay_proportions is not None:
            # Case where the thicknesses of all layers (as a fraction of total domain thickness) 
            # are given as a list in the lay_proportions parameter
            nlay = len(self.lay_proportions)
            allp = np.cumsum(self.lay_proportions)
        elif self.lay_decay is None or self.lay_decay <= 1:
            # Case where the thicknesses of all layers are constant (i.e. all layers have the 
            # same thickness, which is the total domain thickness divided by the number of layers)
            nlay = self.nlay
            allp = np.arange(1,nlay+1) / nlay
        else:
            # Case where the thicknesses of the layers increase with depth
            nlay = self.nlay
            allp = np.zeros((nlay))
            for i in range(1, self.nlay+1):
                allp[i-1] = (1-self.lay_decay**i) / (1-self.lay_decay**self.nlay)
        # Bottom definition for each of the layers
        botm = np.ones((self.nlay,len(top[:,0]),len(top[0,:]))) 
        for i in range(1, self.nlay+1):
            # Weighted formula to go from bottom layer (bot) to surface (top)
            botm[i-1] = top  - ((top - bot) * allp[i-1])
            botm[i-1][top<=self.nodata]=self.nodata
        return botm,nlay   

    # %%%% UNSTRUCTURED SPATIAL GRID CREATION
    # Creation methods for unstructured spatial grid
    def _create_sgrid_unstructured(self):
        """
        Create an unstructured spatial grid.
        """
        print('Placeholder - Not implemented yet.')

    # %%%% VERTEX SPATIAL GRID CREATION
    # Creation methods for vertex spatial grid
    def _create_sgrid_vertex(self):
        """
        Create a vertex spatial grid.
        """
        print('Placeholder - Not implemented yet.')    
     
    # %%% TEMPORAL GRID CREATION
    
    
#%% NOTES
# TODO: DEM crs and length unit (as imported from .tif file) should be checked and 
# reprojected if necessary