# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
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
import whitebox
from hydromodpy.tools import get_logger
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False

logger = get_logger(__name__)

#%% CLASS

class Settings:
    """
    Class with some update functions for groundwater model parameters.
    """
    
    def __init__(self):
        logger.info('Initializing settings module for groundwater parameters')
        
        self.update_well_pumping()
    
    #%% UPDATE
    
    def update_model_name(self, model_name):
        """
        Update the model name of the simulation.

        Parameters
        ----------
        model_name : str
            Name of simulation.
        """
        self.model_name = model_name
    
    def update_box_model(self, box):
        """
        Define the extend of the groundwater flow model simulation.

        Parameters
        ----------
        box : bool
            True of False.
            If True, the model is run at the maximal box scale of the buffered model domain.
            If False, the model is run at the buffered model domain scale.
        """
        self.box = box
    
    def update_sink_fill(self, sink_fill):
        self.sink_fill = sink_fill
    
    def update_bc_sides(self, bc_left, bc_right):
        """
        Apply boundary conditions on the side of the groundwater flow model.

        Parameters
        ----------
        bc_left : float
            Value of head-constant boundary condition on the left side (column) of 2D matrix.
        bc_right : TYPE
            Value of head-constant boundary condition on the right side (column) of 2D matrix.
        """
        self.bc_left = bc_left
        self.bc_right = bc_right
        
    def update_simulation_state(self, sim_state):
        """
        Define the type of simulation.

        Parameters
        ----------
        sim_state : str
            Two options with 'steady' and 'transient'.
            If 'steady', input forcing is only one value.
        """
        self.sim_state = sim_state
        
    def update_check_model(self, plot_cross=True, check_grid=True, cross_ylim=[]):
        """
        Activate of not the cross-section plot of the aquifer model.

        Parameters
        ----------
        plot_cross : bool, optional
            The default is True.
        """
        self.plot_cross = plot_cross
        self.cross_ylim = cross_ylim
        self.check_grid = check_grid
    
    def update_input_particles(self, zone_partic, # path of a raster (injecting where pixels > 0)
                                     cell_div = 1, # 1
                                     zloc_div = False,
                                     bore_depth = None, # '[0,5,10] for 3 particles
                                     track_dir = 'forward', # backward
                                     sel_random = None,
                                     sel_slice = None):
        """
        Select the zones and configurations to inject particles.

        Parameters
        ----------
        zone_partic : str, optional
            Path of the raster used to inject particles: where value > 0.
            The default is 'domain', so the particles are injected where the model domain area > 0m. 
        track_dir: str
            Choice 'forward' or 'backward' particle tracking method.
            The default is 'forward'.
        bore_depth: list
            [Not stable, currently in development]
            If not None, inject a particle in the z direction (vertical), at the center position of each lays.
        cell_div: int
            Fix the number of particles injected uniformly distributed for each cell.
            If 3 is set, 9 particles will be inejcted (3x*3y)
            The dault is 1.
        zloc_div: bool
            If True, 'cell_div' is also applied vetically for the cells.
            If cell_div is 3 and zloc_div is True, 18 particles will be injected (3x*3y*3z).
            The default is False.
        sel_random: int
            Select randomly where inject a total number of particles.
        sel_random: int
            Select with slicing value where particles.
        """
        self.zone_partic = zone_partic
        self.cell_div = cell_div
        self.zloc_div = zloc_div
        self.bore_depth = bore_depth
        self.track_dir = track_dir
        self.sel_random = sel_random
        self.sel_slice = sel_slice
    
    def update_dis_perlen(self, dis_perlen=False):
        """
        Activate the split discretization of recharge with time length.

        Parameters
        ----------
        dis_perlen : bool, optional
            The default is False.
        """
        self.dis_perlen = dis_perlen
        
    def update_well_pumping(self, well_coords=[], well_fluxes=[]):
        """
        Add wells and associated fluxes across the model domain area.
        
        wells_coord : list
            Inform the outlet coordinates of wells [lay,row,col].
            Example for 2 wells: [ [1,20,30], [1,15,15] ]
        wells_fluxes : list
            Inform the fluxes [L3/T] for each stress-periods, for different wells.
            Example for 2 wells and 5 stress-periods: [ [-100,0,-100,0,-100], [-100,0,-100,0,-100] ]
        """
        self.well_coords=well_coords
        self.well_fluxes=well_fluxes
    
#%% NOTES
        
