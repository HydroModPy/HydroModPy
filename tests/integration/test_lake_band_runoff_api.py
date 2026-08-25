"""Exposed-band (marnage) runoff injected through the MF6 BMI API.

Drives a graded-bed lake at CONSTANT stage (high then low) through libmf6 with the
exposed-band runoff callback, and checks that the lake RUNOFF the callback sets
from the live stage is zero at full pool and ``rate * exposed_area`` once the
higher-bed cells emerge. This proves the BMI coupling end to end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("modflowapi")
pytest.importorskip("xmipy")

from hydromodpy.solver.modflow6.api.api_runner import (  # noqa: E402
    Mf6ApiContext,
    Mf6ApiStep,
    run_mf6_api,
)
from hydromodpy.solver.modflow6.support.lake_band_runoff import (  # noqa: E402
    LakeBandRunoffSpec,
    make_exposed_band_runoff_callback,
)
from hydromodpy.solver.modflow_common.binaries import (  # noqa: E402
    ensure_solver_binary,
    locate_solver_binary,
    managed_bin_dir,
)

_no_lib = locate_solver_binary(managed_bin_dir(), "libmf6") is None

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.skipif(_no_lib, reason="libmf6 shared library not in cache"),
]

_BED = [10.0, 20.0, 30.0, 40.0, 50.0]
_AREA = 100.0 * 100.0  # dx = dy = 100
_RATE = 2.0e-7  # m/s


def _build(ws: Path, exe: str):
    import flopy

    ncol, ncpl, nlay = 5, 5, 1
    vertices, vid, v = [], {}, 0
    for j in range(2):
        for i in range(ncol + 1):
            vid[(i, j)] = v
            vertices.append([v, i * 100.0, (1 - j) * 100.0])
            v += 1
    cell2d = []
    for c in range(ncol):
        nodes = [vid[(c, 0)], vid[(c + 1, 0)], vid[(c + 1, 1)], vid[(c, 1)]]
        cell2d.append([c, (c + 0.5) * 100.0, 50.0, 4, *nodes])

    sim = flopy.mf6.MFSimulation(sim_name="band", sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim, time_units="seconds", nper=2, perioddata=[(1.0, 1, 1.0), (1.0, 1, 1.0)]
    )
    flopy.mf6.ModflowIms(sim, complexity="COMPLEX", outer_maximum=200, inner_maximum=200)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="band", save_flows=True, newtonoptions="NEWTON")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=nlay,
        ncpl=ncpl,
        nvert=len(vertices),
        top=np.array(_BED),
        botm=np.full((nlay, ncpl), -50.0),
        vertices=vertices,
        cell2d=cell2d,
        idomain=np.ones((nlay, ncpl), dtype=int),
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=1.0)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, steady_state={0: True, 1: True})
    flopy.mf6.ModflowGwfic(gwf, strt=55.0)
    connectiondata = [[0, i, (0, i), "VERTICAL", 1.0e-6, 0.0, 0.0, 0.0, 0.0] for i in range(ncpl)]
    flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_flows=True,
        save_flows=True,
        surfdep=0.1,
        nlakes=1,
        ntables=0,
        packagedata=[[0, 60.0, len(connectiondata), "lac0"]],
        connectiondata=connectiondata,
        perioddata={
            0: [[0, "STATUS", "CONSTANT"], [0, "STAGE", 60.0]],
            1: [[0, "STATUS", "CONSTANT"], [0, "STAGE", 35.0]],
        },
    )
    flopy.mf6.ModflowGwfoc(gwf, budget_filerecord="band.cbc", saverecord=[("BUDGET", "ALL")])
    sim.write_simulation(silent=True)
    return sim


def test_band_runoff_injected_from_live_stage(tmp_path: Path) -> None:
    _build(tmp_path, str(ensure_solver_binary("mf6")))

    spec = LakeBandRunoffSpec(
        pkg="LAK",
        lake_index=0,
        bed=np.array(_BED),
        area=np.full(5, _AREA),
        rate_per_period=(_RATE, _RATE),
        base_runoff_per_period=(0.0, 0.0),
    )
    band = make_exposed_band_runoff_callback([spec])
    recorded: dict[int, float] = {}

    def callback(ctx: Mf6ApiContext) -> None:
        band(ctx)
        if ctx.step is Mf6ApiStep.timestep_end:
            recorded[ctx.kper] = float(ctx.read_lake_runoff(pkg="LAK")[0])

    assert run_mf6_api(tmp_path, callback), "BMI run did not converge"

    # Full pool (stage 60): nothing exposed -> no band runoff.
    assert recorded[0] == pytest.approx(0.0, abs=1e-9)
    # Drawn down (stage 35): beds 40 and 50 emerge -> 2 cells -> rate * 20000 m2.
    assert recorded[1] == pytest.approx(_RATE * 2 * _AREA, rel=1e-6)
