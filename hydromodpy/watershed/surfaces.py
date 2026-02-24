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
import os
import numpy as np
import pandas as pd
import geopandas as gpd
from netCDF4 import Dataset
import sys
import matplotlib.pyplot as plt
from hydromodpy.tools import get_logger

# Root
from os.path import dirname, abspath
df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
root_dir = (dirname(abspath(__file__)))
sys.path.append(root_dir)

# HydroModPy
from hydromodpy.tools import toolbox
from hydromodpy.tools import setup_simulation_log
from hydromodpy.watershed.initializing_config import InitializingConfig

logger = get_logger(__name__)

#%% CLASS

class Surfaces:
    """
    XXX
    """

    def __init__(self, aquifer_top, # str .tifpath or 2-D array,
                       aquifer_bottom, # str .tif path or 2-D array,
                       ):
                       
        """
        XXX
        """
        self.aquifer_top = aquifer_top
        self.aquifer_bottom = aquifer_bottom

#%% FUNCTIONS


#%% NOTES
