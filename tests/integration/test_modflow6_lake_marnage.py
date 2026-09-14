"""Active-littoral (marnage) physics: MF6 toggles recharge per cell with stage.

The bed_reconstruction ``dynamic_area`` mode keeps lakebed cells ACTIVE with their
top set to the bathymetric bed and one VERTICAL LAK connection each. MODFLOW 6
then sets ``ibound=IWETLAKE`` on a cell while the lake stage is above its bed
(recharge/ET zeroed, lake exchange computed) and resets it to active when the
shoreline recedes below the bed (recharge resumes). This is the documented
"Drying and Rewetting of Sections of a Lake" behaviour (TM 6-A55) and the no
double-count guidance of lak.tex.

This test builds a tiny model with a graded bed and a CONSTANT-stage lake that is
high in period 1 (whole bed submerged) and low in period 2 (the higher-bed cells
emerge), and checks that areal recharge enters the model only once cells emerge.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# Cell bed (= cell top) increases along the row; a graded littoral.
_BED = [10.0, 20.0, 30.0, 40.0, 50.0]
_STAGE_HIGH = 60.0  # period 1: above every bed -> all cells submerged
_STAGE_LOW = 35.0  # period 2: cells with bed 40, 50 emerge and must recharge
_RCH_RATE = 1.0e-7  # m/s over every cell


def _build_marnage_model(ws: Path, exe: str):
    import flopy

    nrow, ncol = 1, 5
    dx = dy = 100.0
    nlay = 1

    vertices: list[list[float]] = []
    vid: dict[tuple[int, int], int] = {}
    v = 0
    for j in range(nrow + 1):
        for i in range(ncol + 1):
            vid[(i, j)] = v
            vertices.append([v, i * dx, (nrow - j) * dy])
            v += 1
    cell2d: list[list[float]] = []
    for r in range(nrow):
        for c in range(ncol):
            nodes = [vid[(c, r)], vid[(c + 1, r)], vid[(c + 1, r + 1)], vid[(c, r + 1)]]
            cell2d.append([r * ncol + c, (c + 0.5) * dx, (nrow - r - 0.5) * dy, 4, *nodes])

    ncpl = nrow * ncol
    top = np.array(_BED, dtype=float)  # cell top = bathymetric bed (marnage carve)
    botm = np.full((nlay, ncpl), -50.0)
    idomain = np.ones((nlay, ncpl), dtype=int)  # marnage: cells stay ACTIVE

    name = "marnage"
    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim, time_units="seconds", nper=2, perioddata=[(1.0, 1, 1.0), (1.0, 1, 1.0)]
    )
    flopy.mf6.ModflowIms(sim, complexity="COMPLEX", outer_maximum=200, inner_maximum=200)
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname=name, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=nlay,
        ncpl=ncpl,
        nvert=len(vertices),
        top=top,
        botm=botm,
        vertices=vertices,
        cell2d=cell2d,
        idomain=idomain,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=1.0)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, steady_state={0: True, 1: True})
    flopy.mf6.ModflowGwfic(gwf, strt=55.0)
    flopy.mf6.ModflowGwfrcha(gwf, recharge=_RCH_RATE)

    # One VERTICAL LAK connection per active cell (matches build_lake_connectiondata
    # with dynamic_area=True); MF6 sets belev = cell top = the graded bed.
    connectiondata = [[0, i, (0, i), "VERTICAL", 1.0e-6, 0.0, 0.0, 0.0, 0.0] for i in range(ncpl)]
    packagedata = [[0, _STAGE_HIGH, len(connectiondata), "lac0"]]
    perioddata_lak = {
        0: [[0, "STATUS", "CONSTANT"], [0, "STAGE", _STAGE_HIGH]],
        1: [[0, "STATUS", "CONSTANT"], [0, "STAGE", _STAGE_LOW]],
    }
    flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_flows=True,
        save_flows=True,
        surfdep=0.1,
        nlakes=1,
        ntables=0,
        packagedata=packagedata,
        connectiondata=connectiondata,
        perioddata=perioddata_lak,
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{name}.cbc",
        saverecord=[("BUDGET", "ALL")],
        printrecord=[("BUDGET", "ALL")],
    )
    return sim, name


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_marnage_exposed_cells_recharge_submerged_do_not(tmp_path):
    flopy = pytest.importorskip("flopy")
    from flopy.utils.mflistfile import Mf6ListBudget

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    exe = str(ensure_solver_binary("mf6"))
    sim, name = _build_marnage_model(tmp_path, exe)
    sim.write_simulation(silent=True)
    ok, _ = sim.run_simulation(silent=True)
    assert ok, "marnage MF6 model failed to converge"

    inc, _cum = Mf6ListBudget(str(tmp_path / f"{name}.lst")).get_dataframes()
    rch_col = next(c for c in inc.columns if c.upper().startswith(("RCHA_IN", "RCH_IN")))
    rch_in = inc[rch_col].to_numpy(dtype=float)

    # Period 1: whole bed submerged -> every cell is IWETLAKE -> no areal recharge.
    assert rch_in[0] == pytest.approx(0.0, abs=1e-6)
    # Period 2: the higher-bed cells emerge and recharge as land.
    assert rch_in[1] > rch_in[0]
    # Quantitatively, the two emerged cells (bed 40, 50) recharge at the full rate.
    expected = 2 * _RCH_RATE * (100.0 * 100.0)
    assert rch_in[1] == pytest.approx(expected, rel=0.05)
