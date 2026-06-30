"""Process-isolated MODFLOW 6 API runner: serial and thread-parallel.

``run_mf6_api_isolated`` runs each libmf6 solve in its own ``spawn`` child
process so the in-process API runner is safe under the calibration
``ThreadPoolExecutor``. These tests write tiny single-lake models, then:

* run one isolated solve and confirm it converges and writes the LAK stage;
* run four isolated solves CONCURRENTLY in threads and confirm all converge --
  the in-process runner would corrupt libmf6's shared global state here, but a
  child-per-solve gives each its own library instance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("modflowapi")

from hydromodpy.solver.modflow6.api_subprocess import run_mf6_api_isolated  # noqa: E402
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary  # noqa: E402


def _write_single_lake(ws: Path, exe: str) -> None:
    import flopy

    nlay, nrow, ncol = 2, 5, 5
    sim = flopy.mf6.MFSimulation(sim_name="lakd", sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 1, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="lakd", save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    top = np.full((nrow, ncol), 100.0)
    botm = np.stack([np.full((nrow, ncol), 90.0), np.full((nrow, ncol), 50.0)])
    flopy.mf6.ModflowGwfdis(
        gwf, nlay=nlay, nrow=nrow, ncol=ncol, delr=10.0, delc=10.0, top=top, botm=botm
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=0.1, save_flows=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    chd = [
        [(1, r, c), 80.0]
        for r in range(nrow)
        for c in range(ncol)
        if r in (0, nrow - 1) or c in (0, ncol - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    lake_rc = [(r, c) for r in (1, 2, 3) for c in (1, 2, 3)]
    conn = [
        [0, i, (1, r, c), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0] for i, (r, c) in enumerate(lake_rc)
    ]
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        print_stage=True,
        save_flows=True,
        boundnames=True,
        nlakes=1,
        ntables=1,
        packagedata=[[0, 95.0, len(conn), "lac0"]],
        connectiondata=conn,
        tables=[[0, "lac0.laktab"]],
        stage_filerecord="lakd.lak.stage",
        perioddata={0: [[0, "RAINFALL", 0.0]]},
        surfdep=0.1,
    )
    flopy.mf6.ModflowUtllaktab(
        gwf,
        nrow=3,
        ncol=3,
        table=[(90.0, 0.0, 0.0), (95.0, 450.0, 90.0), (100.0, 900.0, 90.0)],
        filename="lac0.laktab",
        parent_file=lak,
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="lakd.hds",
        budget_filerecord="lakd.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_isolated_api_run_converges(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    _write_single_lake(tmp_path, exe)
    assert run_mf6_api_isolated(tmp_path) is True
    # The solve ran in a child process and wrote its outputs to the shared
    # workspace, so the parent sees the normal-termination listing + LAK stage.
    assert (tmp_path / "mfsim.lst").is_file()
    assert (tmp_path / "lakd.lak.stage").is_file()


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_isolated_api_is_thread_parallel_safe(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    workspaces = []
    for i in range(4):
        ws = tmp_path / f"trial{i}"
        _write_single_lake(ws, exe)
        workspaces.append(ws)
    # Four concurrent isolated solves: each gets its own libmf6 child process, so
    # the shared global state that bars in-process thread-parallel api never bites.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_mf6_api_isolated, workspaces))
    assert results == [True, True, True, True]
