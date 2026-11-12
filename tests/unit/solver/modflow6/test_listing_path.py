"""Name of the MODFLOW 6 listing file (at most 16 characters).

MF6 writes the listing under its 16-character model name, while the .hds and .cbc keep
the full run name.
"""

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

# MF6 writes the listing under its 16-character model name, while the .hds and .cbc
# keep the full run name, so a raw-name lookup would silently empty mass_balance.
LONG_NAME = "nancon_intermittence_mf6"
LISTING_STEMS = [
    pytest.param("canut_paper_mf6", "canut_paper_mf6", id="short name"),
    pytest.param(LONG_NAME, mf6_safe_name(LONG_NAME), id="long name is truncated"),
    # Windows paths hand the extractor the safe name directly: no double hash.
    pytest.param(mf6_safe_name(LONG_NAME), mf6_safe_name(LONG_NAME), id="already safe"),
    pytest.param("run one", "run_one", id="spaced name"),
]


@pytest.mark.parametrize(("name", "stem"), LISTING_STEMS)
def test_listing_follows_the_model_name(name: str, stem: str) -> None:
    assert _listing_path(Path("/out"), name) == Path("/out") / f"{stem}.lst"


def test_listing_name_max_16() -> None:
    stem = _listing_path(Path("/out"), LONG_NAME).stem

    assert stem != LONG_NAME
    assert len(stem) <= 16
