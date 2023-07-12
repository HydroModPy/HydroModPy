# -*- coding: utf-8 -*-
"""

Created on 2023

@author: Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy

"""

#%% LIBRAIRIES

# Modules
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

#%% NOTES
        
        