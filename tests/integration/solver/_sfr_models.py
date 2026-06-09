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
