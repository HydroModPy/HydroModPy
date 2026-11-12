"""Removal of the files a solver wrote in its output folder."""

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


def _solver_folder(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "solver_output"
    folder.mkdir()
    for name in names:
        (folder / name).write_text(name)
    return folder


def test_cleanup_removes_the_folder(tmp_path: Path) -> None:
    folder = _solver_folder(tmp_path, "model.hds", "model.cbc", "model.lst")

    cleanup_solver_files(folder)

    assert not folder.exists()


def test_cleanup_keeps_the_listed_extensions(tmp_path: Path) -> None:
    folder = _solver_folder(tmp_path, "model.hds", "model.lst", "model.nam")

    cleanup_solver_files(folder, keep={".lst", ".nam"})

    assert (folder / "model.lst").exists()
    assert (folder / "model.nam").exists()
    assert not (folder / "model.hds").exists()


def test_cleanup_removes_subfolders_when_keeping_extensions(tmp_path: Path) -> None:
    folder = _solver_folder(tmp_path, "model.lst")
    (folder / "temp").mkdir()
    (folder / "temp" / "scratch.lst").write_text("x")

    cleanup_solver_files(folder, keep={".lst"})

    assert [p.name for p in folder.iterdir()] == ["model.lst"]
