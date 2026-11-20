"""EVT extinction depth (m) read from the MODFLOW 6 configuration, 1.0 m by default."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import NetworkError
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.workspace.workspace import resolve_bin_path
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.modflow6 import run as run_module
from hydromodpy.solver.modflow6.api import api_runner
from hydromodpy.solver.modflow6.api.api_runner import (
    Mf6ApiContext,
    Mf6ApiStep,
    _resolve_api_success,
    _simulation_reached_normal_termination,
    run_mf6_api,
)
from hydromodpy.solver.modflow6.builders.recharge import build_evt_stress_period_data
from hydromodpy.solver.modflow6.extractors.flow import _listing_path
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.run import _stopping
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common import binaries
from hydromodpy.solver.modflow_common.binaries import (
    ensure_platform_executable,
    ensure_solver_library,
    exe_filename,
    locate_solver_binary,
)
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_evt_extinction_depth() -> None:
    model = toy_model()
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.full((2, 3), 10.0), botm=np.zeros((1, 2, 3))
    )

    def extinction_depth() -> float:
        spd = build_evt_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=np.zeros(6, dtype=bool),
            stream_support_mask=np.zeros(6, dtype=bool),
        )
        assert spd is not None
        # Record layout: [layer, cell_id, surface, rate, extinction_depth].
        return spd[1][0][4]

    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 2.5}}
    )
    assert extinction_depth() == pytest.approx(2.5)

    # The default config keeps 1.0 m.
    model.modflow_config = _coerce_modflow6_config({})
    assert extinction_depth() == pytest.approx(1.0)
