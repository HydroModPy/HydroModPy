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
from parameters import Recharge



# %% CLASS


class Evapotranspiration(Recharge):

    """ 
    WIP
    Attributes
    ----------
    x_coord: list of float
        Lambert 93 X coordinates of piezometers

    Methods
    -------

    """

    # %%% CONSTRUCTOR
    def __init__(self,
                 name: str = 'evapo',
                 output_name = 'evt'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default simulation: constant, homogeneous recharge 
        self.set_iptpar(genmtd_sdis = 'homogeneous',
                        genmtd_tdis = 'constant',
                        genmtd_surf = 'from_dem',
                        value       = 0,
                        lenuni      = 'm',
                        itmuni      = 'd') 
        
    # %%% DICTIONARY GENERATION
    def _dict_generation(self):
        """
        WIP - Description
        """
        # reprojects input data chronicles into master time discretization
        self._tdis_generation()
        # get spatial grid for each time period as a dict
        evtdata = self._sdis_generation()
        # get surface for evapotranspiration
        evtsurf = self._surf_generation() 
        # result formatting and export
        resdict = {'evtdata': evtdata,
                   'evtsurf': evtsurf}        
        return resdict
    
    def _surf_generation(self):
        """
        WIP - Description
        """
        genmtd = self.get_iptpar['genmtd_surf']
        if genmtd == 'from_dem':
            sgrid = self.get_csdpar['sgrid']
            dem   = sgrid.top
            evtsurf = dem

        return evtsurf
      

# %% NOTES
# TODO@TB: descriptions