"""MODFLOW 6 runs with the Intel Fortran output buffer.

The buffer turns tens of thousands of small writes per time step into a few, which
took a daily model on Windows from 6.7 s to 0.38 s per simulated day. The head,
budget and binary observation files are the same byte for byte. An observation CSV
comes out garbled under the buffer, so a model that writes one runs without it, and
a value the user set wins.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.solver.modflow_common import progress as runner
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.progress import (
    FORTRAN_BUFFER_ENV,
    run_simulation_with_progress,
    writes_text_observations,
)

NPER = 5


def _simulation(workspace: Path, *, observations: str = ""):
    import flopy

    sim = flopy.mf6.MFSimulation(
        sim_name="m", sim_ws=str(workspace), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(sim, nper=NPER, perioddata=[(86400.0, 1, 1.0)] * NPER)
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m", save_flows=True)
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=4, ncol=4, delr=100.0, delc=100.0, top=50.0, botm=0.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-4, save_flows=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=40.0)
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[[(0, 0, 0), 40.0]])
    flopy.mf6.ModflowGwfrcha(gwf, recharge={k: 1e-8 * (k + 1) for k in range(NPER)})
    if observations == "csv":
        chd.obs.initialize(
            filename="m.chd.obs", continuous={"m.chd.obs.csv": [("q", "chd", (0, 0, 0))]}
        )
    elif observations == "binary":
        chd.obs.initialize(
            filename="m.chd.obs",
            continuous={("m.chd.obs.bin", "binary"): [("q", "chd", (0, 0, 0))]},
        )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="m.hds",
        budget_filerecord="m.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    return sim


def _environment_of_the_run(sim, monkeypatch: pytest.MonkeyPatch) -> dict[str, str] | None:
    seen: dict[str, object] = {}

    def fake(command, cwd, on_line, env=None):
        seen["env"] = env
        return True, []

    monkeypatch.setattr(runner, "run_executable", fake)
    run_simulation_with_progress(sim, NPER)
    return seen["env"]  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("observations", "buffered"), [("", True), ("binary", True), ("csv", False)]
)
def test_the_buffer_is_on_unless_an_observation_is_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, observations: str, buffered: bool
) -> None:
    monkeypatch.delenv(FORTRAN_BUFFER_ENV, raising=False)
    sim = _simulation(tmp_path, observations=observations)

    env = _environment_of_the_run(sim, monkeypatch)

    assert writes_text_observations(sim) is not buffered
    assert (env is not None and env[FORTRAN_BUFFER_ENV] == "TRUE") is buffered
    assert FORTRAN_BUFFER_ENV not in os.environ


def test_a_value_the_user_set_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FORTRAN_BUFFER_ENV, "FALSE")
    sim = _simulation(tmp_path)

    assert _environment_of_the_run(sim, monkeypatch) is None


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_the_buffer_leaves_heads_budgets_and_observations_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = {}
    for value in ("TRUE", "FALSE"):
        monkeypatch.setenv(FORTRAN_BUFFER_ENV, value)
        sim = _simulation(tmp_path / value, observations="binary")
        success, lines = run_simulation_with_progress(sim, NPER)
        assert success, lines[-5:]
        names = ("m.hds", "m.cbc", "m.chd.obs.bin")
        outputs[value] = {name: (tmp_path / value / name).read_bytes() for name in names}

    assert outputs["TRUE"] == outputs["FALSE"]
