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

# %% LIBRAIRIES

# Python
import pandas as pd
import numpy as np
# Hydromodpy
from tools import Process


# %% CLASS


class InitialBoundaryCondition(Process):

    """ 
    TODO@TB: Description WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'ibnd',
                 output_name: str = 'ibound'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default initial BC generation: all cells active for flow calculation
        self.set_iptpar(genmtd_sdis = 'all_active')
 
        # Default option & path for master spatial discretization 
        self.set_iptpar(sgrid = 'from_shrenv')
        self.set_shrpar(sgrid = 'sdis')
        
        
    # %%% INSTANCIATION OF ABSTRACT METHODS FROM PROCESS CLASS
    def preprocessing(self,shrenv):
        """
        Extract and store input data from files / shared environment.
        """
        # master spatial & time discretization from shared environment
        if self._iptpar['sgrid'] == 'from_shrenv':
            sgridnam = self.get_shrpar['sgrid']
            sgrid = self.get_envar(shrenv,sgridnam)
            self._set_csdpar(sgrid = sgrid)   
            
        self._isPreprocessed = True
        
    def processing(self,shrenv: dict = {}):
        """
        Processing and export results.
        """
        # check if process has been preprocessed
        if self._isPreprocessed is False:
            print('Error: Process '+self.get_name+' has not been pre-processed and cannot be processed.')
            return shrenv
        # 3D matrix
        output = self._matrix_generation()
        # clear consolidated parameters (optional)
        if self.clear_csdpar_option is True:
            self.clear_csdpar()
        # update shared environment with process outputs
        shrenv.update({self.get_output_name: output})
        return shrenv
        
    # %%% MATRIX GENERATION    
    def _matrix_generation(self):
        """
        WIP - Description
        """
        # matrix generation
        genmtd_sdis = self.get_iptpar['genmtd_sdis']
        if   genmtd_sdis == 'all_active':
            resmat = self._genmat_all_active()          
    
        return resmat
    
    
    def _genmat_all_active(self):
        """
        WIP - Description
        """
        botm   = self.get_csdpar['sgrid'].botm
        
        resmat = botm * 0 + 1
        return resmat
        
      

# %% NOTES
# TODO@TB: methods descriptions