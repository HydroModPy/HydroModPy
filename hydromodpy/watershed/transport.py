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

class Transport:
    """
    Class with some update functions for transport (concentration) model parameters.
    """
    
    def __init__(self):
        logger.info('Initializing transport module for concentration parameters')
        
    #%% UPDATE
    
    def update_mt3dms_parameters(self,
                                 spc_name: str='NO3',
                                 sconc_init: float=0,
                                 sconc_input = 0,
                                 disp_long: float=0,
                                 disp_transh: float=0,
                                 disp_transv: float=0,
                                 diffu_coeff: float=0,
                                 react_order: int=None, # for MT3DM: 0, 1, 100
                                 rate_decay: float=0,
                                 plot_conc: bool=True,
                                 verbose: bool=True
                                 ):
        """
        Update the model name of the simulation.

        Parameters
        ----------
        model_name : str
            Name of simulation.
        """
        
        self.spc_name = spc_name
        self.sconc_init = sconc_init
        self.sconc_input = sconc_input
        self.disp_long = disp_long
        self.disp_transh = disp_transh
        self.disp_transv = disp_transv
        self.diffu_coeff = diffu_coeff
        self.react_order = react_order
        self.rate_decay = rate_decay
        self.plot_conc = plot_conc
        self.verbose = verbose
        
#%% NOTES
        
