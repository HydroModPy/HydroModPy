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

logger = get_logger(__name__)

#%% CLASS

class Initializing:
    """
    XXX.
    """
    
    def __init__(self,
                 catch_name: str='Default',
                 out_dir_path: str=None,
                 ):
        """
        Parameters
        ----------
        catch_name : string
            The default is 'Default'.
        """
        self.catch_name = catch_name
        self.out_dir_path = out_dir_path

        self.catch_folder = os.path.join(out_dir_path, catch_name)
        toolbox.create_folder(self.catch_folder)

        setup_simulation_log(self.catch_folder)

        self.stable_folder = os.path.join(self.catch_folder, 'results_stable')
        toolbox.create_folder(self.stable_folder)

        self.simulations_folder = os.path.join(self.catch_folder, 'results_simulations')
        toolbox.create_folder(self.simulations_folder)

        self.calibration_folder = os.path.join(self.catch_folder, 'results_calibration')
        toolbox.create_folder(self.calibration_folder)

        self.add_data_folder = os.path.join(self.stable_folder, 'add_data')
        toolbox.create_folder(self.add_data_folder)

        self.figure_folder = os.path.join(self.stable_folder, '_figures')
        toolbox.create_folder(self.figure_folder)

#%% FUNCTIONS


        

#%% NOTES
