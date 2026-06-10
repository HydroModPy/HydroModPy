"""Shared standalone-SFR MF6 model for the solver integration tests.

A 5x5 / single-layer DISV grid carrying a two-reach delineated trace split into
per-cell sub-reaches by the production builder, fed by a constant headwater
inflow plus a distributed runoff, with NO lake anywhere.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders.sfr import (
    build_sfr_package_args,
    resolve_sfr_networks,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.geographic.core.sfr_network import SfrReachRow, SfrReachTrace

INFLOW_M3S = 0.05
RUNOFF_M3S = 0.02
MODEL_NAME = "sfrsa"
NETWORK_ID = "net0"


def _mesh() -> SolverMesh:
    top = np.full((5, 5), 100.0)
    botm = np.full((1, 5, 5), 50.0)
    return SolverMesh.from_structured_arrays(nrow=5, ncol=5, top=top, botm=botm, dx=10.0, dy=10.0)


def _trace() -> SfrReachTrace:
    head = LineString([(2.0, 48.0), (25.0, 25.0)])
    tail = LineString([(25.0, 25.0), (48.0, 3.0)])
    rows = (
        SfrReachRow(
            ifno=0,
            line=head,
            rlen=float(head.length),
            rtp=95.5,
            rgrd=1e-3,
            strahler=1,
            area_km2=1.0,
            upstream=(),
            downstream=(1,),
            is_terminal_to_lake=False,
        ),
        SfrReachRow(
            ifno=1,
            line=tail,
            rlen=float(tail.length),
            rtp=95.0,
            rgrd=1e-3,
            strahler=1,
            area_km2=2.0,
            upstream=(0,),
            downstream=(),
            is_terminal_to_lake=False,
        ),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def _fake_model(connected: bool) -> SimpleNamespace:
    payload = {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": _trace(),
        "connected_to_aquifer": connected,
        "headwater_inflow": {"kind": "constant", "value": INFLOW_M3S, "units": "m3/s"},
        "runoff": {"kind": "constant", "value": RUNOFF_M3S, "units": "m3/s"},
    }
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": {NETWORK_ID: payload}}),
        nper=1,
        perlen=np.asarray([86400.0]),
        steady=(True,),
        time_grid=None,
        time_units="seconds",
        model_output_name=MODEL_NAME,
    )


def run_standalone_sfr_model(ws: Path, *, connected: bool):
    """Build, write and run the standalone model; return (network, last obs row).

    The production ``build_sfr_package_args`` output drives the flopy assembly,
    the obs CSV and the ``{stem}.sfr.meta.json`` sidecar exactly as ``build.py``
    writes them.
    """
    import flopy

    exe = str(ensure_solver_binary("mf6"))
    mesh = _mesh()
    model = _fake_model(connected)
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    args = build_sfr_package_args(model, networks=networks)
    assert args is not None
    args.pop("mover_records", None)
    obs_continuous = args.pop("obs_continuous")
    sfr_obs_meta = args.pop("sfr_obs_meta")
    args.pop("ts_specs", None)

    sim = flopy.mf6.MFSimulation(sim_name=MODEL_NAME, sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 1, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname=MODEL_NAME, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    disv_kwargs = mesh.to_disv_kwargs()
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **disv_kwargs,
        idomain=mesh.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-4, save_specific_discharge=True)
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    boundary = [
        [(0, cid), 95.0] for cid in range(mesh.n_cells) if cid % 5 in (0, 4) or cid // 5 in (0, 4)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: boundary})

    sfr = flopy.mf6.ModflowGwfsfr(gwf, pname="SFR", **args)
    sfr.obs.initialize(
        filename=f"{MODEL_NAME}.sfr.obs",
        digits=10,
        print_input=False,
        continuous=obs_continuous,
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{MODEL_NAME}.hds",
        budget_filerecord=f"{MODEL_NAME}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    (ws / f"{MODEL_NAME}.sfr.meta.json").write_text(json.dumps(sfr_obs_meta, sort_keys=True))
    success, _buff = sim.run_simulation(silent=True)
    assert success, "standalone SFR MF6 run did not converge"

    with open(ws / f"{MODEL_NAME}.sfr.obs.csv", encoding="utf-8") as fh:
        last = list(csv.DictReader(fh))[-1]
    obs = {key.upper(): float(value) for key, value in last.items()}
    return networks[NETWORK_ID], obs


COUPLED_MODEL_NAME = "sfrlak"


def _coupled_mesh_and_lake() -> tuple[SolverMesh, list[int]]:
    """8x8 / 2-layer mesh with a 3x3 lake footprint in the low (south-east) corner."""
    nrow = ncol = 8
    top = np.full((nrow, ncol), 100.0)
    botm = np.stack([np.full((nrow, ncol), 90.0), np.full((nrow, ncol), 50.0)])
    lake_cells = [r * ncol + c for r in (0, 1, 2) for c in (5, 6, 7)]
    inactive = np.zeros((2, nrow * ncol), dtype=bool)
    inactive[0, lake_cells] = True
    mesh = SolverMesh.from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=botm, dx=10.0, dy=10.0, inactive_mask=inactive
    )
    return mesh, lake_cells


def _coupled_trace() -> SfrReachTrace:
    """A stream descending towards the lake corner; the tail reach feeds the lake."""
    head = LineString([(5.0, 75.0), (35.0, 45.0)])
    tail = LineString([(35.0, 45.0), (47.0, 28.0)])
    rows = (
        SfrReachRow(
            ifno=0,
            line=head,
            rlen=float(head.length),
            rtp=95.5,
            rgrd=1e-3,
            strahler=1,
            area_km2=1.0,
            upstream=(),
            downstream=(1,),
            is_terminal_to_lake=False,
        ),
        SfrReachRow(
            ifno=1,
            line=tail,
            rlen=float(tail.length),
            rtp=95.0,
            rgrd=1e-3,
            strahler=1,
            area_km2=2.0,
            upstream=(0,),
            downstream=(),
            is_terminal_to_lake=True,
        ),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def run_coupled_sfr_lak_model(ws: Path, *, route_drainage: bool = False):
    """Run a coupled SFR -> MVR -> LAK model; return (network, sfr obs, lak obs).

    The SFR side comes from the production builder (``outflow_to_lake = 1``); the
    LAK side is a minimal single-lake package whose 9 VERTICAL connections leak to
    layer 1. The MVR block is assembled exactly as ``build.py`` does: records
    merged, packages derived from the rows, ``maxpackages`` from
    ``mover_package_count``. With ``route_drainage`` a low-elevation drain is
    added away from the reaches and its discharge converges to the nearest reach
    through the production DRN -> SFR MVR routing.
    """
    import flopy

    from hydromodpy.solver.modflow6.builders.mvr import (
        build_mvr_period_records,
        mover_package_count,
    )
    from hydromodpy.solver.modflow6.builders.sfr import (
        build_drainage_mover_records,
        remove_drain_cells,
        sfr_drain_cells_to_drop,
    )

    exe = str(ensure_solver_binary("mf6"))
    mesh, lake_cells = _coupled_mesh_and_lake()

    payload = {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": _coupled_trace(),
        "headwater_inflow": {"kind": "constant", "value": INFLOW_M3S, "units": "m3/s"},
        "runoff": {"kind": "constant", "value": RUNOFF_M3S, "units": "m3/s"},
        "outflow_to_lake": 1,
        "route_drainage": route_drainage,
    }
    model = SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": {NETWORK_ID: payload}}),
        nper=1,
        perlen=np.asarray([86400.0]),
        steady=(True,),
        time_grid=None,
        time_units="seconds",
        model_output_name=COUPLED_MODEL_NAME,
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)

    # Static drains away from the stream, below the ambient head so they flow;
    # with route_drainage their discharge converges to the nearest reach.
    drn_spd: dict[int, list[list[float]]] = {0: [[0, cid, 92.5, 1e-4] for cid in (9, 10, 17, 18)]}
    drn_spd = remove_drain_cells(drn_spd, cells=sfr_drain_cells_to_drop(networks))
    drainage_movers = build_drainage_mover_records(
        networks, drn_spd=drn_spd, cell_centroids=mesh.cell_centroids()
    )

    args = build_sfr_package_args(model, networks=networks, external_mover=bool(drainage_movers))
    assert args is not None
    mover_records = args.pop("mover_records")
    obs_continuous = args.pop("obs_continuous")
    sfr_obs_meta = args.pop("sfr_obs_meta")
    args.pop("ts_specs", None)

    sim = flopy.mf6.MFSimulation(sim_name=COUPLED_MODEL_NAME, sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 5, 1.2)])
    # COMPLEX matches the production default (resolve_ims_complexity): its
    # backtracking + DBD under-relaxation damp the two-way LAK-aquifer stage
    # oscillation that stalls MODERATE on this fixture.
    flopy.mf6.ModflowIms(
        sim,
        complexity="COMPLEX",
        linear_acceleration="BICGSTAB",
        outer_maximum=300,
        inner_maximum=300,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim,
        modelname=COUPLED_MODEL_NAME,
        save_flows=True,
        newtonoptions="NEWTON UNDER_RELAXATION",
    )
    disv_kwargs = mesh.to_disv_kwargs()
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **disv_kwargs,
        idomain=mesh.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-4, k33=1e-5, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=93.0)
    ncol = 8
    border = [
        [(1, cid), 93.0]
        for cid in range(mesh.n_cells)
        if cid % ncol in (0, ncol - 1) or cid // ncol in (0, ncol - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: border})
    flopy.mf6.ModflowGwfdrn(
        gwf,
        pname="DRN",
        stress_period_data=drn_spd,
        save_flows=True,
        mover=bool(drainage_movers),
    )

    connectiondata = [
        [0, iconn, (1, cell), "VERTICAL", 0.01, 0.0, 0.0, 0.0, 0.0]
        for iconn, cell in enumerate(lake_cells)
    ]
    laktab = [(90.0, 0.0, 0.0), (95.0, 4050.0, 810.0), (100.0, 8100.0, 810.0)]
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        nlakes=1,
        ntables=1,
        packagedata=[[0, 92.0, len(connectiondata), "lac0"]],
        connectiondata=connectiondata,
        tables=[[0, "lac0.laktab"]],
        boundnames=True,
        surfdep=0.1,
        mover=True,
        save_flows=True,
        stage_filerecord=f"{COUPLED_MODEL_NAME}.lak.stage",
        budget_filerecord=f"{COUPLED_MODEL_NAME}.lak.cbc",
    )
    flopy.mf6.ModflowUtllaktab(
        gwf, nrow=3, ncol=3, table=laktab, filename="lac0.laktab", parent_file=lak
    )
    lak.obs.initialize(
        filename=f"{COUPLED_MODEL_NAME}.lak.obs",
        digits=10,
        print_input=False,
        continuous={
            f"{COUPLED_MODEL_NAME}.lak.obs.csv": [
                ("lac0_stage", "stage", (0,)),
                ("lac0_from_mvr", "from-mvr", (0,)),
            ]
        },
    )

    sfr = flopy.mf6.ModflowGwfsfr(gwf, pname="SFR", **args)
    sfr.obs.initialize(
        filename=f"{COUPLED_MODEL_NAME}.sfr.obs",
        digits=10,
        print_input=False,
        continuous=obs_continuous,
    )

    mvr_rows = build_mvr_period_records(drainage_movers) + build_mvr_period_records(mover_records)
    packages = sorted({(str(row[0]),) for row in mvr_rows} | {(str(row[2]),) for row in mvr_rows})
    flopy.mf6.ModflowGwfmvr(
        gwf,
        pname="MVR",
        maxmvr=len(mvr_rows),
        maxpackages=mover_package_count(mvr_rows),
        packages=packages,
        perioddata={0: mvr_rows},
    )

    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{COUPLED_MODEL_NAME}.hds",
        budget_filerecord=f"{COUPLED_MODEL_NAME}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    (ws / f"{COUPLED_MODEL_NAME}.sfr.meta.json").write_text(
        json.dumps(sfr_obs_meta, sort_keys=True)
    )
    success, _buff = sim.run_simulation(silent=True)
    assert success, "coupled SFR-LAK MF6 run did not converge"

    with open(ws / f"{COUPLED_MODEL_NAME}.sfr.obs.csv", encoding="utf-8") as fh:
        sfr_obs = {k.upper(): float(v) for k, v in list(csv.DictReader(fh))[-1].items()}
    with open(ws / f"{COUPLED_MODEL_NAME}.lak.obs.csv", encoding="utf-8") as fh:
        lak_obs = {k.upper(): float(v) for k, v in list(csv.DictReader(fh))[-1].items()}
    return networks[NETWORK_ID], sfr_obs, lak_obs
