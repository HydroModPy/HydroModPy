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


# %% CLASS

class SGrid_Generation:
    """
    Class for creating a spatial grid.
    """
    
    # %%% INITIALIZATION
    # Initialization
    def __init__(self):
        # --- PARAMETERS
        # Default parameter for choosing type of spatial grid to create
        self._sgrid_type  = 'structured' #TODO: only structured implemented for now, but unstructured and vertex grid types will be implemented in the future
        # Default parameters for structured spatial grid creation
        self._lenuni          = 'm'     # Master length unit for the model #TODO: for now, must also be the same length unit of the DEM (no conversion of length units for DEM implemented yet)
        self._top_path        = None    # File path to .tif top surface of domain (= DEM)
        self._crs             = None    # Coodinate Reference System; ex: 'EPSG:2154'
        self._genmtd_bot      = None    # Method used to generate bottom surface of domain: 'filepath','raster','constant_thickness','constant_altitude'
        self._bot_path        = None    # File path to .tif bottom surface of domain
        self._bot_raster      = None    # Raster of bottom surface of domain (#TODO: ad-hoc solution for integration in modflow solver; must have the same dimensions as top surface; not checked here!)
        self._thick           = None    # Total thickness of the domain
        self._zbot            = None    # Altitude of the bottom of the domain
        self._genmtd_lay      = None    # Method used to generate the vertical layering of the domain: 'constant','decay','list' 
        self._lay_proportions = None    # List of lay thickness, expressed as fraction of total domain thickness
        self._lay_decay       = None    # Exponent for power law increase of layer thickness with depth (>1)
        self._nlay            = None    # Number of layers
        # Default advanced parameters for spatial grid creation
        self._nodata          = -9999
        # --- INITIALIZATION
        # Initialization of flags for checking if  parameters for spatial grid 
        # creation have not been modified since last grid creation
        self._sgrid_created = False
        # Initialization of storage of created spatial grid
        self._sgrid         = None
        

    # %%% RUN SPATIAL GRID GENERATION
    # Spatial grid generation
    def run(self):
        if not self._sgrid_created:
            self._create_sgrid()
        return self._sgrid

    # %%% SETTERS AND GETTERS FOR PARAMETERS FOR SPATIAL GRID CREATION
    # Setter and getter for lenuni
    @property
    def lenuni(self):
        return self._lenuni
    @lenuni.setter
    def lenuni(self, value):
        self._lenuni = value
        self._sgrid_created = False

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

    # Setter and getter for genmtd_bot
    @property
    def genmtd_bot(self):
        return self._genmtd_bot
    @genmtd_bot.setter
    def genmtd_bot(self, value):
        self._genmtd_bot = value
        self._sgrid_created = False    

    # Setter and getter for bot_path
    @property  
    def bot_path(self):
        return self._bot_path
    @bot_path.setter
    def bot_path(self, value):
        self._bot_path = value
        self._sgrid_created = False

    # Setter and getter for bot_raster
    @property
    def bot_raster(self):
        return self._bot_raster
    @bot_raster.setter
    def bot_raster(self, value):
        self._bot_raster = value
        self._sgrid_created = False

    # Setter and getter for thick
    @property
    def thick(self):
        return self._thick
    @thick.setter
    def thick(self, value):
        self._thick = value
        self._sgrid_created = False

    # Setter and getter for zbot
    @property
    def zbot(self):
        return self._zbot
    @zbot.setter
    def zbot(self, value):
        self._zbot = value
        self._sgrid_created = False

    # Setter and getter for genmtd_lay
    @property
    def genmtd_lay(self):
        return self._genmtd_lay
    @genmtd_lay.setter
    def genmtd_lay(self, value):
        self._genmtd_lay = value
        self._sgrid_created = False

    # Setter and getter for lay_proportions
    @property
    def lay_proportions(self):
        return self._lay_proportions
    @lay_proportions.setter
    def lay_proportions(self, value):
        self._lay_proportions = value
        self._sgrid_created = False

    # Setter and getter for lay_decay
    @property
    def lay_decay(self):
        return self._lay_decay
    @lay_decay.setter
    def lay_decay(self, value):
        self._lay_decay = value
        self._sgrid_created = False
        
    # Setter and getter for nlay
    @property
    def nlay(self):
        return self._nlay
    @nlay.setter
    def nlay(self, value):
        self._nlay = value
        self._sgrid_created = False

    # Setter and getter for nodata
    @property
    def nodata(self):
        return self._nodata
    @nodata.setter
    def nodata(self, value):
        self._nodata = value
        self._sgrid_created = False

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
        top,delc,delr,xoff,yoff,nrow,ncol = self._create_hgrid_structured()
        # vertical structured grid
        botm,nlay = self._create_vgrid_structured(top)
        # formating and storage as StructuredGrid class from flopy
        sgrid = StructuredGrid(delc = delc,
                               delr = delr,
                               top  = top,
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
        xoff = top.bounds.left
        yoff = top.bounds.bottom
        top  = top.read(1)
        top[top <= self.nodata] = self.nodata
        return top,delc,delr,xoff,yoff,nrow,ncol
    
    # vertical structured grid
    def _create_vgrid_structured(self,top):
        """
        Create the vertical grid for a structured spatial grid.
        """
        # Definition of the bottom layer of the domain
        if self.genmtd_bot == 'filepath':
            bot = rasterio.open(self.bot_path)
            bot = bot.read(1)
            bot[top<=self.nodata]=self.nodata
        if self.genmtd_bot == 'raster':
            bot = self.bot_raster
            bot[top<=self.nodata]=self.nodata
        elif self.genmtd_bot == 'constant_thickness':
            bot = top - self.thick        # Matrix for constant thickness case
            bot[top<=self.nodata]=self.nodata
        elif self.genmtd_bot == 'constant_altitude':
            bot = top * 0 + self.zbot             # Matrix for constant altitude case
            bot[top<=self.nodata]=self.nodata
        # Parameters for proportions of the thciknesses of all layers as a fraction of total domain thickness
        if self.genmtd_lay == 'list':
            # Case where the thicknesses of all layers (as a fraction of total domain thickness) 
            # are given as a list in the lay_proportions parameter
            nlay = len(self.lay_proportions)
            allp = np.cumsum(self.lay_proportions)
        elif self.genmtd_lay == 'constant':
            # Case where the thicknesses of all layers are constant (i.e. all layers have the 
            # same thickness, which is the total domain thickness divided by the number of layers)
            nlay = self.nlay
            allp = np.arange(1,nlay+1) / nlay
        elif self.genmtd_lay == 'decay':
            # Case where the thicknesses of the layers increase with depth
            nlay = self.nlay
            allp = np.zeros((nlay))
            for i in range(1, nlay+1):
                allp[i-1] = (1-self.lay_decay**i) / (1-self.lay_decay**nlay)
        # Bottom definition for each of the layers
        botm = np.ones((nlay,len(top[:,0]),len(top[0,:]))) 
        for i in range(1, nlay+1):
            # Weighted formula to go from bottom layer (bot) to surface (top)
            botm[i-1] = top  - ((top - bot) * allp[i-1])
            botm[i-1][bot<=self.nodata]=self.nodata
        return botm,nlay   

    # %%%% UNSTRUCTURED SPATIAL GRID CREATION
    # Creation methods for unstructured spatial grid
    def _create_sgrid_unstructured(self):
        """
        Create an unstructured spatial grid.
        """
        print('Placeholder - Unstructured spatial grid not implemented yet.')

    # %%%% VERTEX SPATIAL GRID CREATION
    # Creation methods for vertex spatial grid
    def _create_sgrid_vertex(self):
        """
        Create a vertex spatial grid.
        """
        print('Placeholder - Vertex spatial grid not implemented yet.')    
     
#%% NOTES
# TODO: DEM crs and length unit (as imported from .tif file) should be checked and 
# reprojected if necessary