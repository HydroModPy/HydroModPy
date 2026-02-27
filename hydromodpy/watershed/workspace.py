# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

# %% LIBRARIES

import os
import sys
from os.path import abspath, dirname

from hydromodpy.tools import get_logger, setup_simulation_log, toolbox
from hydromodpy.watershed.workspace_config import WorkspaceConfig

df = dirname(dirname(abspath(__file__)))
sys.path.append(df)
root_dir = dirname(abspath(__file__))
sys.path.append(root_dir)

logger = get_logger(__name__)


class Workspace:
    """
    Prepare and expose the folder structure for one watershed workspace.

    This class keeps the same behavior as the historical `Initializing`
    implementation, with a clearer name that reflects its responsibility.
    """

    def __init__(self, config: WorkspaceConfig):
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

        self.add_data_folder = self.stable_folder / "add_data"
        toolbox.create_folder(self.add_data_folder)

        self.figure_folder = self.stable_folder / "_figures"
        toolbox.create_folder(self.figure_folder)

        self.bin_path = os.path.join(os.path.dirname(df), "bin")
