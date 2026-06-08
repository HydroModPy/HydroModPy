"""MF6 LAK driven by a piecewise (csv-then-constant) lake forcing.

A tiny single-lake DISV model is run over a four-period daily transient. The
lake inflow is declared as a :class:`FlowWellForcingPiecewiseConfig` whose first
segment reads a csv chronicle (days 1-2) and whose second segment is a constant
(days 3-4). The production lake builder ``build_lake_period_data`` resolves it to
a TS6 STEPWISE series; this test asserts the series the builder emits matches the
shared ``resolve_period_values_from_forcing`` output and that MF6 runs with it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellForcingPiecewiseConfig
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders.lake import build_lake_period_data
from hydromodpy.solver.modflow6.common.time_series import attach_time_series
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

# Four daily stress periods: 2000-01-01 .. 2000-01-04.
_CSV_INFLOW = (5.0, 9.0)
_CONST_INFLOW = 3.0


def _daily_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2000-01-01"),
        end=pd.Timestamp("2000-01-04"),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


class _FakeTimeGrid:
    def __init__(self, window: ResolvedSimulationTimeWindow) -> None:
        self.window = window


class _FakeProcessSpecific:
    def __init__(self, mode: str, min_periods: int) -> None:
        self.lak_forcing_mode = mode
        self.ts6_min_periods = min_periods


class _FakeConfig:
    def __init__(self, mode: str, min_periods: int) -> None:
        self.process_specific = _FakeProcessSpecific(mode, min_periods)


class _FakeModel:
    def __init__(self, window: ResolvedSimulationTimeWindow, perlen: np.ndarray) -> None:
        self.time_grid = _FakeTimeGrid(window)
        self.nper = int(len(perlen))
        self.perlen = perlen
        self.modflow_config = _FakeConfig(mode="ts6", min_periods=0)


def _piecewise_forcing(csv_path: Path) -> FlowWellForcingPiecewiseConfig:
    return FlowWellForcingPiecewiseConfig(
        segments=[
            {
                "start": "2000-01-01",
                "end": "2000-01-03",
                "forcing": {
                    "kind": "csv",
                    "path_file": str(csv_path),
                    "date_column": "date",
                    "value_column": "value",
                    "units": "m3/s",
                },
            },
            {
                "start": "2000-01-03",
                "forcing": {"kind": "constant", "value": _CONST_INFLOW, "units": "m3/s"},
            },
        ],
        units="m3/s",
    )


def _build_single_lake_disv(
    ws: Path,
    exe: str,
    *,
    perlen: np.ndarray,
    perioddata_lak: dict[int, list[list[object]]],
    ts_series,
):
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

    name = "lakpw"
    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(ws), exe_name=exe)
    perioddata = [(float(plen), 1, 1.0) for plen in perlen]
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=int(len(perlen)), perioddata=perioddata)
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
    attach_time_series(lak, ts_series, filename=f"{name}.lak.ts")
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


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_piecewise_lake_forcing_drives_mf6_and_matches_resolver(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))

    window = _daily_window()
    boundaries = build_simulation_time_boundaries(window)
    nper = len(boundaries) - 1
    perlen = np.asarray(
        [(boundaries[i + 1] - boundaries[i]).total_seconds() for i in range(nper)],
        dtype=float,
    )
    expected_inflow = [*_CSV_INFLOW, _CONST_INFLOW, _CONST_INFLOW]

    csv_path = tmp_path / "inflow.csv"
    csv_path.write_text(
        f"date,value\n2000-01-01,{_CSV_INFLOW[0]}\n2000-01-02,{_CSV_INFLOW[1]}\n",
        encoding="utf-8",
    )
    forcing = _piecewise_forcing(csv_path)

    # The shared resolver yields csv values for Jan/Feb and the constant for Mar/Apr.
    resolved = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=window,
        nper=nper,
        label="flow.sinks_sources.lakes.lac0.inflow",
    )
    assert resolved == expected_inflow

    # The production lake builder routes the same piecewise forcing to a TS6 series.
    model = _FakeModel(window, perlen)
    rows, ts_series = build_lake_period_data(model, lakes={"lac0": {"inflow": forcing}})
    assert len(rows) == 1
    assert rows[0] == [0, "inflow", "lak0_inflow"]
    assert isinstance(rows[0][2], str)
    assert len(ts_series) == 1
    spec = ts_series[0]
    # The per-period TS6 breakpoints reproduce the resolver values exactly.
    assert list(spec.values[:nper]) == pytest.approx(expected_inflow)
    assert spec.values[-1] == pytest.approx(expected_inflow[-1])
    assert len(spec.times) == nper + 1

    perioddata_lak = {0: rows}
    ws = tmp_path / "run"
    ws.mkdir()
    sim, name = _build_single_lake_disv(
        ws, exe, perlen=perlen, perioddata_lak=perioddata_lak, ts_series=ts_series
    )
    ok, _ = sim.run_simulation(silent=True)
    assert ok, "piecewise-driven LAK run did not converge"

    # The model genuinely consumed the external piecewise series via TS6 FILEIN.
    lak_text = (ws / f"{name}.lak").read_text().upper()
    assert "TS6" in lak_text and "FILEIN" in lak_text
    ts_text = (ws / f"{name}.lak.ts").read_text().upper()
    assert "STEPWISE" in ts_text

    stage = _read_stage(ws, name)
    assert stage.shape[0] == nper
    assert np.all(np.isfinite(stage))
