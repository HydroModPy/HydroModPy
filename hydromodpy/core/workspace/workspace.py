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

from pathlib import Path

from hydromodpy.core.tools import get_logger, setup_simulation_log, toolbox
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry

logger = get_logger(__name__)


def _resolve_bin_path() -> str:
    """Resolve the executable folder with repo-root priority."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "bin",  # <repo>/bin
        here.parents[2] / "bin",  # <repo>/hydromodpy/bin (legacy fallback)
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


class Workspace:
    """
    Prepare and expose the folder structure for one project workspace.

    This class keeps the same behavior as the historical `Initializing`
    implementation, with a clearer name that reflects its responsibility.
    """

    def __init__(self, config: WorkspaceConfig):
        self.paths = WorkspacePathRegistry.from_config(config)
        self.project_root = self.paths.project_root
        self.workspace_root = self.paths.workspace_root
        self.catch_name = self.paths.catch_name

        toolbox.create_folder(self.project_root)
        setup_simulation_log(self.project_root)

        self.stable_folder = self.paths.stable_folder
        toolbox.create_folder(self.stable_folder)

        self.simulations_folder = self.paths.simulations_folder
        toolbox.create_folder(self.simulations_folder)

        self.calibration_folder = self.paths.calibration_folder
        toolbox.create_folder(self.calibration_folder)

        self.add_data_folder = self.paths.add_data_folder
        toolbox.create_folder(self.add_data_folder)

        self.figure_folder = self.paths.figures_folder
        toolbox.create_folder(self.figure_folder)

        self.bin_path = _resolve_bin_path()

        # Backwards-compatible aliases
        self.catch_folder = self.project_root
        self.data_path = self.paths.data_path
