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
from pathlib import Path

from hydromodpy.core.io.filesystem import create_folder
from hydromodpy.core.logging import get_logger, setup_simulation_log
from hydromodpy.core.state.cache import get_cache_bin_dir
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry

logger = get_logger(__name__)


def _resolve_bin_path() -> str:
    """Resolve the folder that holds solver executables.

    Resolution order:

    1. ``HYDROMODPY_BIN`` env var, if set (explicit override; useful for
       shared HPC deployments and CI).
    2. The HydroModPy-managed cache (``~/.cache/hydromodpy/bin/`` and
       platform equivalents). Solvers lazily populate it on first use
       via :func:`hydromodpy.solver.modflow_common.ensure_solver_binary`.
    """
    env = os.environ.get("HYDROMODPY_BIN")
    if env:
        return str(Path(env).expanduser().resolve())

    return str(get_cache_bin_dir())


class Workspace:
    """
    Prepare and expose the folder structure for one project workspace.

    This class keeps the same behavior as the historical `Initializing`
    implementation, with a clearer name that reflects its responsibility.
    """

    def __init__(self, config: WorkspaceConfig):
        self.paths = WorkspacePathRegistry.from_config(config)
        self.project_root = self.paths.project_root
        self.root = self.paths.root
        self.catalog_path = self.paths.catalog_path
        self.data_dir = self.paths.data_dir
        self.simulations_dir = self.paths.simulations_dir
        self.catch_name = self.paths.catch_name

        create_folder(self.project_root)
        setup_simulation_log(self.project_root)

        self.figure_folder = self.paths.figures_folder
        self.solver_scratch_folder = self.paths.solver_scratch_folder

        self.bin_path = _resolve_bin_path()
