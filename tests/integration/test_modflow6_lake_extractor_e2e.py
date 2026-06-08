"""End-to-end LAK extraction on a tiny single-lake DISV model.

A 5x5 / 2-layer DISV grid with a 3x3 surface lake whose bed is hung above a
low-head aquifer (perimeter CHD at 80 m, lake starting at 95 m) so the lake
drains downward through its VERTICAL connections. We run MF6, then run the
``Modflow6OutputAdapter`` over the real solver outputs and assert the LAK series
land in the right structures with the right keys and signs:

* stage / volume / surface-area parse under ``station_id = lake:lac0`` and are
  NOT divided by the TDIS time unit (states, not rates);
* the lake-aquifer exchange (``gwf_exchange``) is negative -- the lake loses
  water to the aquifer -- and equals the under-dam leakage here (all VERTICAL
  connections), and is also written to the budget table as ``lak_gwf``;
* the spillway (``ext_outflow``) is a rate in m3/s.

The obs spec and JSON sidecar are built through the production
``build_lake_obs_spec`` so the integration covers the real obs naming and the
extractor's sidecar-driven re-keying.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import build_lake_obs_spec
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow6.extractors.lake import lake_station_id
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary


class _RecordingStore:
    """Minimal SimulationStore double capturing the extractor's writes."""

    def __init__(self) -> None:
        self.timeseries: list[dict] = []
        self.budgets: list[dict] = []

    def write_time(self, sim_id, values, *, epoch=None, calendar=None, units=None) -> None:
        del sim_id, values, epoch, calendar, units

    def write_field(self, sim_id, name, t, values, n_timesteps=None, subgroup=None) -> None:
        del sim_id, name, t, values, n_timesteps, subgroup

    def write_budgets(self, sim_id, records) -> None:
        del sim_id
        self.budgets.extend(records)

    def write_mass_balances(self, sim_id, records) -> None:
        del sim_id, records

    def write_timeseries_batch(self, sim_id, records) -> None:
        del sim_id
        self.timeseries.extend(records)

    def open_zarr(self, sim_id):
        # The spatial-mesh export path is out of scope here; make it a no-op by
        # refusing to open a Zarr store (the extractor swallows the failure).
        raise RuntimeError("zarr export disabled in this test")


def _build_single_lake_disv(ws: Path, exe: str):
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
    lake_conn_info = [
        {
            "lake_index": 0,
            "lake_id": "lac0",
            "n_conn": len(connectiondata),
            "vertical_iconns": list(range(len(connectiondata))),
        }
    ]
    outlets = [[0, 0, -1, "WEIR", 99.0, 5.0, 0.0, 0.0]]
    obs_continuous, meta = build_lake_obs_spec(
        stem="lakd", lake_conn_info=lake_conn_info, outlets=outlets
    )

    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_stage=True,
        print_flows=True,
        save_flows=True,
        nlakes=1,
        noutlets=1,
        ntables=1,
        packagedata=packagedata,
        connectiondata=connectiondata,
        tables=[[0, "lac0.laktab"]],
        outlets=outlets,
        perioddata={0: [[0, "RAINFALL", 0.0]]},
        stage_filerecord="lakd.lak.stage",
        budget_filerecord="lakd.lak.cbc",
        budgetcsv_filerecord="lakd.lak.budget.csv",
        surfdep=0.1,
    )
    flopy.mf6.ModflowUtllaktab(
        gwf, nrow=3, ncol=3, table=laktab, filename="lac0.laktab", parent_file=lak
    )
    lak.obs.initialize(
        filename="lakd.lak.obs", digits=10, print_input=False, continuous=obs_continuous
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="lakd.hds",
        budget_filerecord="lakd.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    (ws / "lakd.lak.meta.json").write_text(json.dumps(meta))
    return sim


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_lake_extractor_end_to_end_disv(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    sim = _build_single_lake_disv(tmp_path, exe)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 single-lake DISV run did not converge"

    store = _RecordingStore()
    Modflow6OutputAdapter().extract("sim-lake", tmp_path, store, model_name="lakd")

    station = lake_station_id("lac0")
    by_variable: dict[str, list[float]] = {}
    for record in store.timeseries:
        assert record["station_id"] == station
        by_variable.setdefault(record["variable"], []).append(float(record["value"]))

    # States exist and stay in their native units (the lake started at 95 m and
    # drains, so the final stage sits between the bed (90 m) and the start).
    assert "stage" in by_variable
    assert "volume" in by_variable
    assert "surface_area" in by_variable
    stage = by_variable["stage"][-1]
    assert 90.0 <= stage < 95.0
    # Volume is a positive state (m3), not a per-second rate.
    assert by_variable["volume"][-1] > 0.0

    # The lake-aquifer exchange is negative: the lake loses water to the aquifer.
    assert "gwf_exchange" in by_variable
    exchange = by_variable["gwf_exchange"][-1]
    assert exchange < 0.0

    # Every connection is VERTICAL (under the footprint), so under-dam leakage
    # equals the total exchange.
    assert "seepage_under_dam" in by_variable
    assert by_variable["seepage_under_dam"][-1] == pytest.approx(exchange)

    # The spillway series exists as a rate (no spill here -> 0 m3/s, but present).
    assert "ext_outflow" in by_variable

    # The exchange total also reaches the budget table, with the loss on flux_out.
    lak_budgets = [b for b in store.budgets if b.get("component") == "lak_gwf"]
    assert lak_budgets, "expected a lak_gwf budget row"
    assert lak_budgets[-1]["zone_id"] == station
    assert lak_budgets[-1]["flux_out"] == pytest.approx(abs(exchange))
    assert lak_budgets[-1]["flux_in"] == pytest.approx(0.0)
