"""On Windows, a MODFLOW 6 workspace mf6 cannot open fails with its path named."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import flopy
import pytest

from hydromodpy.core.exceptions import SolverEnvironmentError
from hydromodpy.core.io.filesystem import WINDOWS_PATH_LIMIT
from hydromodpy.solver.modflow6.support import windows_paths
from hydromodpy.solver.modflow6.support.windows_paths import (
    check_mf6_workspace_paths,
    mf6_workspace_files,
)
from tests._helpers.windows_os import WindowsOs


def _simulation(workspace: Path) -> flopy.mf6.MFSimulation:
    sim = flopy.mf6.MFSimulation(sim_name="abc", sim_ws=str(workspace), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim)
    ims = flopy.mf6.ModflowIms(sim, filename="abc_gwf.ims")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="abc", save_flows=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=1,
        nvert=3,
        vertices=[(0, 0.0, 0.0), (1, 1.0, 0.0), (2, 0.0, 1.0)],
        cell2d=[(0, 0.3, 0.3, 3, 0, 1, 2)],
        top=1.0,
        botm=0.0,
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="abc_heads.hds",
        budget_filerecord="abc_budget.cbc",
        saverecord=[("HEAD", "ALL")],
    )
    drn = flopy.mf6.ModflowGwfdrn(gwf, stress_period_data=[((0, 0), 0.5, 1.0)])
    drn.obs.initialize(
        filename="abc.drn.obs",
        continuous={"abc_drain_observations.csv": [("d", "DRN", (0, 0))]},
    )
    return sim


def _workspace_of_length(tmp_path: Path, length: int) -> Path:
    padding = length - len(str(tmp_path)) - 1
    assert padding > 0
    return tmp_path / ("w" * padding)


def test_a_path_mf6_cannot_open_is_named_with_its_length(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Only the observation table, the longest name, ends past the limit.
    workspace = _workspace_of_length(tmp_path, WINDOWS_PATH_LIMIT - 20)
    sim = _simulation(workspace)
    monkeypatch.setattr(windows_paths, "os", WindowsOs())

    with pytest.raises(SolverEnvironmentError) as caught:
        check_mf6_workspace_paths(sim)

    longest = str(workspace / "abc_drain_observations.csv")
    message = str(caught.value)
    assert caught.value.code == "HMPY.E406"
    assert longest in message
    assert f"{len(longest)} characters" in message
    assert "shorter folder" in message
    assert caught.value.context == {"path": longest, "length": len(longest)}


def test_a_workspace_mf6_can_open_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    longest_name = len("/abc_drain_observations.csv")
    workspace = _workspace_of_length(tmp_path, WINDOWS_PATH_LIMIT - longest_name)
    sim = _simulation(workspace)
    monkeypatch.setattr(windows_paths, "os", WindowsOs())

    check_mf6_workspace_paths(sim)

    assert max(len(path) for path in mf6_workspace_files(sim)) == WINDOWS_PATH_LIMIT
