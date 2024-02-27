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
import whitebox
wbt = whitebox.WhiteboxTools()
#wbt.set_compress_rasters(True)
wbt.verbose = False

#%% CLASS

class Settings:
    """
    Class with some update functions for groundwater model parameters.
    """
    
    def __init__(self):
        
        print('Init settings module to set model parameter')
    
    #%% UPDATE
    
    def update_model_name(self, model_name):
        """
        Update the model name of the simulation.

        Parameters
        ----------
        model_name : TYPE
            DESCRIPTION.
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
        """
        ???
        
        Parameters
        ----------
        sink_fill : ???
            ???.
        """
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
        
    def add_inputflow(self, bound_id, fixed_flow_coords, snap_dist,
                      return_flow_series):
        self.inputflow[bound_id] = (fixed_flow_coords, snap_dist, return_flow_series)
        
    def remove_inputflow(self, bound_id):
        self.inputflow.pop(bound_id)
        
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
        
    def update_active_plot(self, plot_cross=True):
        """
        Activate of not the cross-section plot of the aquifer model.

        Parameters
        ----------
        plot_cross : bool, optional
            The default is True.
        """
        self.plot_cross = plot_cross
    
    def update_input_particules(self, zone_partic='domain'):
        """
        Select the limited area to inject particles onto the surface..

        Parameters
        ----------
        zone_partic : str, optional
            'watershed':inject particles only in cells inside watershed boundaries.
            'domain': inject particles in all cells. The default is 'domain'.
        """
        self.zone_partic = zone_partic
    
#%% NOTES
        