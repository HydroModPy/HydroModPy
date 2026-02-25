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
import pandas as pd
import datetime
# Flopy
from flopy.discretization.modeltime import ModelTime

# %% CLASS

class TGrid_Generation:
    """
    Class for creating a temporal grid.
    """
    
    # %%% INITIALIZATION
    # Initialization
    def __init__(self):
        # Default parameters for temporal grid creation
        self._itmuni           = 'd' #TODO: used only to define master time unit for model
        self._sim_state        = 'steady'
        self._genmtd_tgrid     = 'synthetic_regular'
        self._nper             = 1
        self._lenper           = 1
        self._chron_path       = None
        self._chron_dateformat = '%Y-%m-%d %H:%M:%S'
        self._chron_colsep     = '\t'
        self._chron_time_col   = 'Date'
        self._start_datetime   = None
        self._end_datetime     = None
        # Default advanced parameters for temporal grid creation
        self._tsmult           = 1
        self._firstpersteady   = True
        self._temporal_nodata  = -9999   #TODO: is used?
        # Initialization of flags for checking if parameters for temporal grid 
        # creation have not been modified since last grid creation
        self._tgrid_created = False
        # Initialization of storage of created temporal grid
        self._tgrid       = None    

    # %%% RUN TEMPORAL GRID GENERATION
    # Generate temporal grid
    def run(self):
        if not self._tgrid_created:
            self._create_tgrid()
        return self._tgrid

    # %%% SETTERS AND GETTERS FOR PARAMETERS FOR TEMPORAL GRID CREATION
    # Setter and getter for itmuni
    @property
    def itmuni(self):
        return self._itmuni
    @itmuni.setter
    def itmuni(self, value):
        self._itmuni = value
        self._tgrid_created = False

    # Setter and getter for sim_state
    @property
    def sim_state(self):
        return self._sim_state
    @sim_state.setter
    def sim_state(self, value):
        self._sim_state = value
        self._tgrid_created = False
    
    # Setter and getter for genmtd_tgrid
    @property 
    def genmtd_tgrid(self):
        return self._genmtd_tgrid
    @genmtd_tgrid.setter
    def genmtd_tgrid(self, value):
        self._genmtd_tgrid = value
        self._tgrid_created = False

    # Setter and getter for nper
    @property
    def nper(self):
        return self._nper
    @nper.setter
    def nper(self, value):
        self._nper = value
        self._tgrid_created = False

    # Setter and getter for lenper
    @property
    def lenper(self):
        return self._lenper
    @lenper.setter
    def lenper(self, value):
        self._lenper = value
        self._tgrid_created = False
    
    # Setter and getter for chron_path
    @property
    def chron_path(self):
        return self._chron_path
    @chron_path.setter
    def chron_path(self, value):
        self._chron_path = value
        self._tgrid_created = False
    
    # Setter and getter for chron_dateformat
    @property
    def chron_dateformat(self):
        return self._chron_dateformat
    @chron_dateformat.setter
    def chron_dateformat(self, value):
        self._chron_dateformat = value
        self._tgrid_created = False
    
    # Setter and getter for chron_colsep
    @property
    def chron_colsep(self):
        return self._chron_colsep
    @chron_colsep.setter
    def chron_colsep(self, value):
        self._chron_colsep = value
        self._tgrid_created = False
    
    # Setter and getter for chron_time_col
    @property
    def chron_time_col(self):
        return self._chron_time_col
    @chron_time_col.setter
    def chron_time_col(self, value):
        self._chron_time_col = value
        self._tgrid_created = False
    
    # Setter and getter for start_datetime
    @property
    def start_datetime(self):
        return self._start_datetime
    @start_datetime.setter
    def start_datetime(self, value):
        self._start_datetime = value
        self._tgrid_created = False
    
    # Setter and getter for end_datetime
    @property   
    def end_datetime(self):
        return self._end_datetime
    @end_datetime.setter
    def end_datetime(self, value):
        self._end_datetime = value
        self._tgrid_created = False

    # %%% TEMPORAL GRID CREATION
    # Creation methods for temporal grid
    def _create_tgrid(self):
        if self._genmtd_tgrid == 'synthetic_regular':
            self._tgrid = self._create_synthetic_regular_tgrid()
        elif self._genmtd_tgrid == 'from_chron':
            self._tgrid = self._create_tgrid_from_chron()
        # Set flag to True after grid creation
        self._tgrid_created = True

    
    
    
#%% NOTES