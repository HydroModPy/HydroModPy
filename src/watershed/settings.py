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

    #%% INIT
    
    def __init__(self):
        
        print('Init settings module to set model parameter')
    
    #%% UPDATE
    
    def update_model_name(self, model_name):

        self.model_name = model_name
    
    def update_box_model(self, box):

        self.box = box
    
    def update_sink_fill(self, sink_fill):

        self.sink_fill = sink_fill
    
    def update_bc_sides(self, bc_left, bc_right):

        self.bc_left = bc_left
        self.bc_right = bc_right
        
    def update_simulation_state(self, sim_state):
        self.sim_state = sim_state
        
    def update_active_plot(self, plot_cross=True):
        self.plot_cross = plot_cross
    
    def update_input_particules(self, zone_partic='domain'):
        self.zone_partic = zone_partic
    
#%% NOTES
        