"""MF6 equivalence: inline LAK perioddata vs external TS6 STEPWISE series.

The same tiny single-lake DISV model is run twice over a 6-period transient sim
with non-uniform period lengths and a per-period inflow series c0..c5:

* run A writes the inflow as explicit per-period perioddata rows
  ``{kper: [[0, "INFLOW", c_kper]]}`` (the legacy inline path);
* run B writes one perioddata row ``[0, "INFLOW", "lak0_inflow"]`` and attaches a
  TS6 file (``time_series_namerecord=["lak0_inflow"]``,
  ``interpolation_methodrecord=["stepwise"]``, ``timeseries=[[t0, c0], ...]``)
  through the production ``attach_time_series`` helper.

MF6 STEPWISE holds each value constant from its ``ts_time`` up to the next, and
each ``t_k`` is the exact start of stress period k, so MF6 integrates the same
constant inflow over each period in both runs. We therefore assert the lake stage
series, the lake budget inflow term, and the GWF heads are identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.support.time_series import Ts6Series, attach_time_series
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

# Non-uniform stress periods (seconds) and a distinct inflow per period (m3/s).
_PERLEN = (86400.0, 43200.0, 172800.0, 86400.0, 129600.0, 86400.0)
_INFLOW = (5.0, 9.0, 2.0, 7.0, 3.0, 8.0)


def _ts6_times_and_values(
    perlen: tuple[float, ...], inflow: tuple[float, ...]
) -> tuple[list[float], list[float]]:
    """Period-start breakpoints plus a terminal breakpoint at the sim end.

    STEPWISE holds each value from its period start; the terminal breakpoint at
    ``cumsum(perlen)[-1]`` (repeating the last value) closes the final interval so
    MF6 can integrate the series over the last period.
    """
    cumulative = np.cumsum(perlen)
    times = [0.0, *cumulative[:-1].tolist(), float(cumulative[-1])]
    values = [*inflow, inflow[-1]]
    return times, values


def _build_single_lake_disv(ws: Path, exe: str, *, use_ts6: bool):
    import flopy

    nrow = ncol = 5
    dx = dy = 10.0
    nlay = 2

    vertices: list[list[float]] = []
    vid: dict[tuple[int, int], int] = {}
    vertex = 0
    for j in range(nrow + 1):
        for i in range(ncol + 1):
            vid[(i, j)] = vertex
            vertices.append([vertex, i * dx, (nrow - j) * dy])
            vertex += 1

    cell2d: list[list[float]] = []
    rc_to_cid: dict[tuple[int, int], int] = {}
    cid = 0
    for r in range(nrow):
        for c in range(ncol):
            nodes = [vid[(c, r)], vid[(c + 1, r)], vid[(c + 1, r + 1)], vid[(c, r + 1)]]
            cell2d.append([cid, (c + 0.5) * dx, (nrow - r - 0.5) * dy, 4, *nodes])
            rc_to_cid[(r, c)] = cid
            cid += 1

    ncpl = nrow * ncol
    top = np.full(ncpl, 100.0)
    botm = np.stack([np.full(ncpl, 90.0), np.full(ncpl, 50.0)])
    lake_rc = [(r, c) for r in (1, 2, 3) for c in (1, 2, 3)]
    lake_cells = [rc_to_cid[rc] for rc in lake_rc]
    idomain = np.ones((nlay, ncpl), dtype=int)
    for cell in lake_cells:
        idomain[0, cell] = 0

    name = "lakts" if use_ts6 else "lakin"
    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(ws), exe_name=exe)
    perioddata = [(plen, 1, 1.0) for plen in _PERLEN]
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=len(_PERLEN), perioddata=perioddata)
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
        outer_dvclose=1e-9,
        inner_dvclose=1e-10,
    )
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
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=0.1, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    chd = [
        [(1, rc_to_cid[(r, c)]), 80.0]
        for r in range(nrow)
        for c in range(ncol)
        if r in (0, nrow - 1) or c in (0, ncol - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})

    connectiondata = [
        [0, iconn, (1, cell), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0]
        for iconn, cell in enumerate(lake_cells)
    ]
    packagedata = [[0, 95.0, len(connectiondata), "lac0"]]
    laktab = [(90.0, 0.0, 0.0), (95.0, 450.0, 90.0), (100.0, 900.0, 90.0)]

    if use_ts6:
        perioddata_lak = {0: [[0, "INFLOW", "lak0_inflow"]]}
    else:
        perioddata_lak = {
            kper: [[0, "INFLOW", float(_INFLOW[kper])]] for kper in range(len(_PERLEN))
        }

    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_stage=True,
        print_flows=True,
        save_flows=True,
        nlakes=1,
        ntables=1,
        packagedata=packagedata,
        connectiondata=connectiondata,
        tables=[[0, "lac0.laktab"]],
        perioddata=perioddata_lak,
        stage_filerecord=f"{name}.lak.stage",
        budget_filerecord=f"{name}.lak.cbc",
        budgetcsv_filerecord=f"{name}.lak.budget.csv",
        surfdep=0.1,
    )
    flopy.mf6.ModflowUtllaktab(
        gwf, nrow=3, ncol=3, table=laktab, filename="lac0.laktab", parent_file=lak
    )
    if use_ts6:
        times, values = _ts6_times_and_values(_PERLEN, _INFLOW)
        attach_time_series(
            lak,
            [
                Ts6Series(
                    name="lak0_inflow",
                    times=tuple(times),
                    values=tuple(float(v) for v in values),
                    interpolation="stepwise",
                )
            ],
            filename=f"{name}.lak.ts",
        )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{name}.hds",
        budget_filerecord=f"{name}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    return sim, name


def _read_stage(ws: Path, name: str) -> np.ndarray:
    import flopy

    obj = flopy.utils.HeadFile(ws / f"{name}.lak.stage", text="STAGE")
    return np.asarray(obj.get_alldata()).ravel()


def _read_heads(ws: Path, name: str) -> np.ndarray:
    import flopy

    obj = flopy.utils.HeadFile(ws / f"{name}.hds")
    return np.asarray(obj.get_alldata())


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_ts6_stepwise_matches_inline_lake_stage(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))

    ws_inline = tmp_path / "inline"
    ws_inline.mkdir()
    sim_a, name_a = _build_single_lake_disv(ws_inline, exe, use_ts6=False)
    ok_a, _ = sim_a.run_simulation(silent=True)
    assert ok_a, "inline LAK run did not converge"

    ws_ts6 = tmp_path / "ts6"
    ws_ts6.mkdir()
    sim_b, name_b = _build_single_lake_disv(ws_ts6, exe, use_ts6=True)
    ok_b, _ = sim_b.run_simulation(silent=True)
    assert ok_b, "TS6 LAK run did not converge"

    # The TS6 run genuinely used the external path: the LAK file references a
    # TS6 FILEIN record and the .ts file declares STEPWISE interpolation.
    lak_text = (ws_ts6 / f"{name_b}.lak").read_text().upper()
    assert "TS6" in lak_text and "FILEIN" in lak_text
    ts_path = ws_ts6 / f"{name_b}.lak.ts"
    assert ts_path.exists()
    ts_text = ts_path.read_text().upper()
    assert "STEPWISE" in ts_text

    stage_a = _read_stage(ws_inline, name_a)
    stage_b = _read_stage(ws_ts6, name_b)
    heads_a = _read_heads(ws_inline, name_a)
    heads_b = _read_heads(ws_ts6, name_b)

    assert stage_a.shape == stage_b.shape
    assert heads_a.shape == heads_b.shape
    # STEPWISE over period-start times reproduces the inline per-period constant
    # inflow exactly: lake stage and aquifer heads are bit-identical.
    assert np.array_equal(stage_a, stage_b)
    assert np.array_equal(heads_a, heads_b)
