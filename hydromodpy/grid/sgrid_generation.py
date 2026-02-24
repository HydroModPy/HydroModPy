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
from typing import Any, Mapping
from pathlib import Path
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
        self._genmtd_top      = 'filepath'  # Method used to generate top surface of domain: 'filepath' (i.e. from a .tif file)
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

    # %%% CONFIGURATION HELPERS
    @classmethod
    def from_config(cls, config_data: Mapping[str, Any]):
        """
        Build a configured SGrid_Generation instance from a dictionary payload.

        Parameters
        ----------
        config_data : mapping
            Configuration mapping. Accepts either:
            - a flat mapping with SGrid keys, or
            - a top-level mapping containing a ``"sgrid"`` section.
        """
        try:
            from .sgrid_config import validate_sgrid_config_data
        except ImportError:
            from sgrid_config import validate_sgrid_config_data

        cfg = validate_sgrid_config_data(config_data)
        obj = cls()
        obj.sgrid_type = cfg["sgrid_type"]
        obj.lenuni = cfg["lenuni"]
        obj.genmtd_top = cfg["genmtd_top"]
        obj.top_path = cfg["top_path"]
        obj.crs = cfg.get("crs")
        obj.genmtd_bot = cfg["genmtd_bot"]
        obj.genmtd_lay = cfg["genmtd_lay"]
        obj.nodata = cfg["nodata"]

        if cfg.get("bot_path") is not None:
            obj.bot_path = cfg["bot_path"]
        if cfg.get("thick") is not None:
            obj.thick = cfg["thick"]
        if cfg.get("zbot") is not None:
            obj.zbot = cfg["zbot"]
        if cfg.get("nlay") is not None:
            obj.nlay = cfg["nlay"]
        if cfg.get("lay_decay") is not None:
            obj.lay_decay = cfg["lay_decay"]
        if cfg.get("lay_proportions") is not None:
            obj.lay_proportions = cfg["lay_proportions"]

        return obj

    @classmethod
    def from_toml(cls, config_path):
        """
        Build a configured SGrid_Generation instance from a TOML file.
        """
        try:
            from .sgrid_config import load_sgrid_toml
        except ImportError:
            from sgrid_config import load_sgrid_toml

        cfg = load_sgrid_toml(config_path)
        return cls.from_config(cfg)

    # %%% SETTERS AND GETTERS FOR PARAMETERS FOR SPATIAL GRID CREATION
    # Setter and getter for sgrid_type
    @property
    def sgrid_type(self):
        return self._sgrid_type
    @sgrid_type.setter
    def sgrid_type(self, value):
        self._sgrid_type = value
        self._sgrid_created = False

    # Setter and getter for lenuni
    @property
    def lenuni(self):
        return self._lenuni
    @lenuni.setter
    def lenuni(self, value):
        self._lenuni = value
        self._sgrid_created = False

    # Setter and getter for genmtd_top    
    @property
    def genmtd_top(self):
        return self._genmtd_top
    @genmtd_top.setter
    def genmtd_top(self, value):
        self._genmtd_top = value
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
        self._validate_runtime_configuration()
        if self._sgrid_type == 'structured':
            self._sgrid = self._create_sgrid_structured()
        elif self._sgrid_type == 'unstructured':
            self._sgrid = self._create_sgrid_unstructured()
        elif self._sgrid_type == 'vertex':
            self._sgrid = self._create_sgrid_vertex()
        self._sgrid_created = True

    def _validate_runtime_configuration(self):
        """
        Validate runtime configuration before spatial grid generation.

        This path is used for direct Python configuration (setters), independently
        from TOML/Pydantic validation.
        """
        if self._sgrid_type is None:
            raise ValueError(
                "sgrid_type is required for spatial grid creation."
            )
        if self._sgrid_type == 'unstructured':
            raise NotImplementedError(
                "Unstructured spatial grid is not implemented yet."
            )
        if self._sgrid_type == 'vertex':
            raise NotImplementedError(
                "Vertex spatial grid is not implemented yet."
            )
        if self._sgrid_type != 'structured':
            raise ValueError(
                f"Unsupported sgrid_type '{self._sgrid_type}'. "
                "Allowed values are: structured, unstructured, vertex."
            )

        if self.genmtd_top != 'filepath':
            raise ValueError(
                f"Unsupported genmtd_top '{self.genmtd_top}'. "
                "Only 'filepath' is currently implemented."
            )
        if self.top_path is None or str(self.top_path).strip() == "":
            raise ValueError("top_path is required when genmtd_top='filepath'.")
        top_path = Path(str(self.top_path)).expanduser()
        if not top_path.exists():
            raise FileNotFoundError(f"Top raster not found: {top_path}")

        if not isinstance(self.nodata, (int, float, np.integer, np.floating)):
            raise TypeError("nodata must be a numeric scalar.")

        valid_bot_methods = {'filepath', 'raster', 'constant_thickness', 'constant_altitude'}
        if self.genmtd_bot not in valid_bot_methods:
            raise ValueError(
                f"Unsupported genmtd_bot '{self.genmtd_bot}'. "
                f"Allowed: {sorted(valid_bot_methods)}"
            )
        if self.genmtd_bot == 'filepath':
            if self.bot_path is None or str(self.bot_path).strip() == "":
                raise ValueError("bot_path is required when genmtd_bot='filepath'.")
            bot_path = Path(str(self.bot_path)).expanduser()
            if not bot_path.exists():
                raise FileNotFoundError(f"Bottom raster not found: {bot_path}")
        elif self.genmtd_bot == 'raster':
            if self.bot_raster is None:
                raise ValueError("bot_raster is required when genmtd_bot='raster'.")
        elif self.genmtd_bot == 'constant_thickness':
            if self.thick is None:
                raise ValueError("thick is required when genmtd_bot='constant_thickness'.")
        elif self.genmtd_bot == 'constant_altitude':
            if self.zbot is None:
                raise ValueError("zbot is required when genmtd_bot='constant_altitude'.")

        valid_lay_methods = {'list', 'constant', 'decay'}
        if self.genmtd_lay not in valid_lay_methods:
            raise ValueError(
                f"Unsupported genmtd_lay '{self.genmtd_lay}'. "
                f"Allowed: {sorted(valid_lay_methods)}"
            )
        if self.genmtd_lay == 'list':
            if self.lay_proportions is None:
                raise ValueError("lay_proportions is required when genmtd_lay='list'.")
            lay_prop = np.asarray(self.lay_proportions, dtype=float)
            if lay_prop.ndim != 1 or lay_prop.size == 0:
                raise ValueError("lay_proportions must be a non-empty 1D sequence.")
            if np.any(lay_prop <= 0):
                raise ValueError("lay_proportions values must be strictly positive.")
            if not np.isclose(np.sum(lay_prop), 1.0, rtol=0.0, atol=1e-6):
                raise ValueError("lay_proportions must sum to 1.0.")
        elif self.genmtd_lay == 'constant':
            if not isinstance(self.nlay, (int, np.integer)) or int(self.nlay) <= 0:
                raise ValueError("nlay must be a strictly positive integer when genmtd_lay='constant'.")
        elif self.genmtd_lay == 'decay':
            if not isinstance(self.nlay, (int, np.integer)) or int(self.nlay) <= 0:
                raise ValueError("nlay must be a strictly positive integer when genmtd_lay='decay'.")
            if self.lay_decay is None or float(self.lay_decay) <= 1:
                raise ValueError("lay_decay must be > 1 when genmtd_lay='decay'.")

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
        # Creates top layer from a .tif file
        if self.genmtd_top == 'filepath':
            with rasterio.open(self.top_path) as top_src:
                nrow = top_src.height
                ncol = top_src.width
                delc = np.array([top_src.transform[0]] * nrow)
                delr = np.array([-top_src.transform[4]] * ncol)
                xoff = top_src.bounds.left
                yoff = top_src.bounds.bottom
                top = top_src.read(1)
            top[top <= self.nodata] = self.nodata
            return top, delc, delr, xoff, yoff, nrow, ncol
        raise ValueError(
            f"Unsupported genmtd_top '{self.genmtd_top}'. "
            "Only 'filepath' is currently implemented."
        )
    
    # vertical structured grid
    def _create_vgrid_structured(self,top):
        """
        Create the vertical grid for a structured spatial grid.
        """
        bot = self._compute_bottom_surface(
            top=top,
            nodata=self.nodata,
            genmtd_bot=self.genmtd_bot,
            bot_path=self.bot_path,
            bot_raster=self.bot_raster,
            thick=self.thick,
            zbot=self.zbot,
        )
        allp, nlay = self._compute_layer_proportions(
            genmtd_lay=self.genmtd_lay,
            nlay=self.nlay,
            lay_decay=self.lay_decay,
            lay_proportions=self.lay_proportions,
        )
        botm = self._build_botm(top=top, bot=bot, nodata=self.nodata, allp=allp)
        return botm, nlay

    @staticmethod
    def _compute_bottom_surface(
        top,
        nodata,
        genmtd_bot,
        bot_path=None,
        bot_raster=None,
        thick=None,
        zbot=None,
    ):
        """
        Compute the bottom surface array from selected bottom-generation method.
        """
        if genmtd_bot == 'filepath':
            with rasterio.open(bot_path) as bot_src:
                bot = bot_src.read(1)
        elif genmtd_bot == 'raster':
            bot = np.asarray(bot_raster)
        elif genmtd_bot == 'constant_thickness':
            bot = np.asarray(top, dtype=float) - float(thick)
        elif genmtd_bot == 'constant_altitude':
            bot = np.zeros_like(top, dtype=float) + float(zbot)
        else:
            raise ValueError(
                f"Unsupported genmtd_bot '{genmtd_bot}'. "
                "Allowed: filepath, raster, constant_thickness, constant_altitude."
            )

        bot = np.asarray(bot, dtype=float)
        if bot.shape != top.shape:
            raise ValueError(
                f"Bottom surface shape mismatch: bot{bot.shape} != top{top.shape}."
            )
        bot[top <= nodata] = nodata
        return bot

    @staticmethod
    def _compute_layer_proportions(genmtd_lay, nlay=None, lay_decay=None, lay_proportions=None):
        """
        Compute cumulative layer proportions (`allp`) and layer count (`nlay`).
        """
        if genmtd_lay == 'list':
            arr = np.asarray(lay_proportions, dtype=float)
            allp = np.cumsum(arr)
            return allp, int(arr.size)
        if genmtd_lay == 'constant':
            nlay_int = int(nlay)
            allp = np.arange(1, nlay_int + 1, dtype=float) / nlay_int
            return allp, nlay_int
        if genmtd_lay == 'decay':
            nlay_int = int(nlay)
            decay = float(lay_decay)
            idx = np.arange(1, nlay_int + 1, dtype=float)
            allp = (1 - decay**idx) / (1 - decay**nlay_int)
            return allp, nlay_int
        raise ValueError(
            f"Unsupported genmtd_lay '{genmtd_lay}'. "
            "Allowed: list, constant, decay."
        )

    @staticmethod
    def _build_botm(top, bot, nodata, allp):
        """
        Build layer bottom elevations from top, bottom and cumulative proportions.
        """
        top = np.asarray(top, dtype=float)
        bot = np.asarray(bot, dtype=float)
        allp = np.asarray(allp, dtype=float)
        if allp.ndim != 1 or allp.size == 0:
            raise ValueError("allp must be a non-empty 1D array.")

        botm = top[None, :, :] - ((top - bot)[None, :, :] * allp[:, None, None])
        botm[:, bot <= nodata] = nodata
        return botm

    # %%%% UNSTRUCTURED SPATIAL GRID CREATION
    # Creation methods for unstructured spatial grid
    def _create_sgrid_unstructured(self):
        """
        Create an unstructured spatial grid.
        """
        raise NotImplementedError('Unstructured spatial grid not implemented yet.')

    # %%%% VERTEX SPATIAL GRID CREATION
    # Creation methods for vertex spatial grid
    def _create_sgrid_vertex(self):
        """
        Create a vertex spatial grid.
        """
        raise NotImplementedError('Vertex spatial grid not implemented yet.')    
     
#%% NOTES
# TODO: DEM crs and length unit (as imported from .tif file) should be checked and 
# reprojected if necessary
