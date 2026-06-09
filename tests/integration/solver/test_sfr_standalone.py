"""Standalone SFR on a tiny DISV model: real MF6 run, budget + routing identity.

A 5x5 / single-layer DISV grid carries a two-reach delineated trace split into
per-cell sub-reaches by the production builder. The network is fed by a constant
headwater inflow and a distributed runoff, with NO lake anywhere: this is the
proof that SFR routes standalone.

Two variants run real MF6 (6.6.3):

* pure routing (``connected_to_aquifer = false``): the terminal EXT-OUTFLOW must
  equal inflow + runoff exactly (no streambed exchange to hide a routing bug);
* connected reaches: the same identity holds once the reach-aquifer exchange is
  added back, and the global GWF budget closes.

Tolerances: rows 44-45 of ``tests/TOLERANCES.md`` (single source of truth).
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders.sfr import (
    build_sfr_package_args,
    resolve_sfr_networks,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.geographic.core.sfr_network import SfrReachRow, SfrReachTrace

# tests/TOLERANCES.md row 44: standalone SFR global budget closure.
_BUDGET_PERCENT_DISCREPANCY = 1.0
# tests/TOLERANCES.md row 45: per-SFR routing identity bands.
_ROUTING_IDENTITY_RTOL = 1e-6
_EXCHANGE_IDENTITY_REL = 1e-2

_INFLOW_M3S = 0.05
_RUNOFF_M3S = 0.02


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
        "headwater_inflow": {"kind": "constant", "value": _INFLOW_M3S, "units": "m3/s"},
        "runoff": {"kind": "constant", "value": _RUNOFF_M3S, "units": "m3/s"},
    }
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": {"net0": payload}}),
        nper=1,
        perlen=np.asarray([86400.0]),
        steady=(True,),
        time_grid=None,
        time_units="seconds",
        model_output_name="sfrsa",
    )


def _run_standalone(ws: Path, *, connected: bool):
    import flopy

    exe = str(ensure_solver_binary("mf6"))
    mesh = _mesh()
    model = _fake_model(connected)
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    args = build_sfr_package_args(model, networks=networks)
    assert args is not None
    args.pop("mover_records", None)
    obs_continuous = args.pop("obs_continuous")
    args.pop("sfr_obs_meta")
    args.pop("ts_specs", None)

    sim = flopy.mf6.MFSimulation(sim_name="sfrsa", sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 1, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="sfrsa", save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
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
        filename="sfrsa.sfr.obs", digits=10, print_input=False, continuous=obs_continuous
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="sfrsa.hds",
        budget_filerecord="sfrsa.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "standalone SFR MF6 run did not converge"

    with open(ws / "sfrsa.sfr.obs.csv", encoding="utf-8") as fh:
        last = list(csv.DictReader(fh))[-1]
    return networks["net0"], {key.upper(): float(value) for key, value in last.items()}


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_sfr_standalone_pure_routing_identity(tmp_path: Path) -> None:
    network, obs = _run_standalone(tmp_path, connected=False)
    terminal = max(reach.ifno for reach in network.reaches)
    outflow = -obs[f"R{terminal}_EXT_OUTFLOW"]  # MF6 reports outflow negative
    expected = _INFLOW_M3S + _RUNOFF_M3S
    # Pure routing: no streambed exchange can hide a mis-route.
    assert outflow == pytest.approx(expected, rel=_ROUTING_IDENTITY_RTOL)
    # Headwater inflow arrived where it was injected.
    assert obs["R0_EXT_INFLOW"] == pytest.approx(_INFLOW_M3S, rel=_ROUTING_IDENTITY_RTOL)

    discrepancy = _last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) <= _BUDGET_PERCENT_DISCREPANCY


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_sfr_standalone_connected_closes_mass_with_exchange(tmp_path: Path) -> None:
    network, obs = _run_standalone(tmp_path, connected=True)
    terminal = max(reach.ifno for reach in network.reaches)
    outflow = -obs[f"R{terminal}_EXT_OUTFLOW"]
    # 'sfr' obs is positive when the stream loses water to the aquifer.
    gw_loss = sum(
        obs[f"R{reach.ifno}_GW_EXCHANGE"] for reach in network.reaches if reach.cellid is not None
    )
    expected = _INFLOW_M3S + _RUNOFF_M3S - gw_loss
    total_in = _INFLOW_M3S + _RUNOFF_M3S
    assert abs(outflow - expected) / total_in <= _EXCHANGE_IDENTITY_REL
    # The streambed exchange is a real, non-zero term in this variant.
    assert gw_loss != pytest.approx(0.0, abs=1e-12)

    discrepancy = _last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) <= _BUDGET_PERCENT_DISCREPANCY
