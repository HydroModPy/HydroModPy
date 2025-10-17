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
from parameters import HydraulicConductivity


# %% CLASS


class VerticalAnisotropyK(HydraulicConductivity):

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
                 name: str = 'vka',
                 output_name: str = 'vka'):
        """
        Initialize method. 

        Parameters
        ----------
        """
        super().__init__(name, output_name)
        
        # Default field generation: homogeneous field
        self.set_iptpar(genmtd_sdis = 'homogeneous',
                        value       = 1)
        # uniteless
        del self._iptpar['lenuni']
        del self._iptpar['itmuni']
    
    # %%% RE-INSTANCIATION OF PARENT CLASS
    # matrix unit conversion into master discretization unit
    def _unit_conversion(self,resmat):
        return resmat

# %% NOTES
# TODO@TB: methods descriptions