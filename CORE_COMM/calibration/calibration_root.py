# -*- coding: utf-8 -*-
"""
Created on Wed Nov 17 12:42:06 2021

@author: Alexandre Gauvain
"""
#Modules
import os

#HydroModPy modules
from calibration import objective_function


def run_calibration(params, watershed, observation = 'streams'):
    # Update hydrodynamic parameters
    watershed.hydrodynamic.update_hyd_cond(params)
    # Name of model
    ident= observation + '_calibration'
    # Run model
    watershed.run_modflow(ident)
    # Use objective function from the type of observation
    if observation == 'streams':
        
        obj_func = objective_function.Streams(watershed.geographic, 
                                   hydrology_stable=os.path.join(watershed.stable_folder, 'hydrology'), 
                                   simulations_folder=os.path.join(watershed.simulations_folder, ident))
    if observation == 'piezometry':
        
        obj_func = objective_function.Piezometry(watershed.piezometry, 
                                                 simulations_folder=os.path.join(watershed.simulations_folder))
    
    indicator = obj_func.get_indicator()
    return (indicator)
        
        