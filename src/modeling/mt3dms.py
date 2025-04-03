# -*- coding: utf-8 -*-
"""
Created on Thu Apr  3 13:06:53 2025

@author: rabherve
"""

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
import os
import sys
import flopy
import flopy.utils.binaryfile as fpu
import numpy as np
from os.path import dirname, abspath
import random
import pickle
import geopandas as gpd
import imageio
import flopy.utils.postprocessing as pp
import whitebox
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

# Root
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)

# HydroModPy
from tools import toolbox
fontprop = toolbox.plot_params(8,15,18,20) # small, medium, interm, large

#%% CLASS

class Modpath:
    """
    Class Modpath.
    
    To build, run particle traccking from modflow simulation.
    """
    
    def __init__(self,
                 geographic: object,
                 model_modflow: object,
                 # Worflow settings
                 model_folder: str='HydroModPy_outputs',
                 model_name: str='Default_modpath',
                 bin_path: str=os.path.join(os.getcwd(),'bin'),
                 # Specific settings
                 zone_partic: str='domain',
                 track_dir: str='forward',
                 bore_depth: list=None,
                 cell_div: int=1,
                 zloc_div: bool=False,
                 sel_random: int=None,
                 sel_slice: int=None):
        """
        Initialize method.

        Parameters
        ----------
        geographic : object
            Geographic object build by HydroModPy.
        """
        
        #%% Initialisation
        
        
        
    #%% PRE-PROCESSING
        
    def pre_processing(self):
        """
        Pre-processing to build the trasnport model.

        Returns
        -------
        None.

        """
        
        #%% Load and import
        
        
        #%% Specific parametrization

        
        #%% Finalize settings
        
        
    #%% PROCESSING
    
    def processing(self,
                   write_model:bool=True,
                   run_model:bool=False):
        """
        Run the trasnport model.

        Parameters
        ----------
        write_model : bool, optional
            Flag to write input files or not. The default is True.
        run_model : bool, optional
            Flag to run model or not. The default is False.

        Returns
        -------
        success_model : bool
            Flag to know if the simulation finished correctly.

        """
        # Create modflow files
        if write_model == True:
            self.mt.write_input()
       
        # Run modflow files
        success_model = False
        if run_model == True:
            verbose = True
            success_model, tempo = self.mt.run_model(silent=not verbose) # True without msg
        
        return success_model

    #%% POST-PROCESSING
    
    def post_processing(self, 
                        model_mt3dms:object):
        """
        Create outputs files.

        Parameters
        ----------
        model_mt3dms : object
            MT3DMS python object.
        """
