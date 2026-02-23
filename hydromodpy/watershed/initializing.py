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

class Initializing:
    """
    Initializes the basic folder structure for the watershed project.

    This class handles the creation of the required directory hierarchy based
    on the provided configuration, ensuring that all subsequent modules have
    the necessary paths available.
    """

    def __init__(self, config: InitializingConfig):
        """
        Initialize the folder creation process.

        Parameters
        ----------
        config : InitializingConfig
            Configuration object containing root folder paths and catchment name.
        """
        self.catch_name = config.catch_name
        self.out_dir_path = config.out_dir_path

        self.catch_folder = config.catch_folder
        toolbox.create_folder(self.catch_folder)

        setup_simulation_log(self.catch_folder)

        self.stable_folder = config.stable_folder
        toolbox.create_folder(self.stable_folder)

        self.simulations_folder = config.simulations_folder
        toolbox.create_folder(self.simulations_folder)

        self.calibration_folder = config.calibration_folder
        toolbox.create_folder(self.calibration_folder)

        self.add_data_folder = self.stable_folder / 'add_data'
        toolbox.create_folder(self.add_data_folder)

        self.figure_folder = self.stable_folder / '_figures'
        toolbox.create_folder(self.figure_folder)

#%% FUNCTIONS




#%% NOTES
