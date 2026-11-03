"""Two lakes + HFB wall + SFR with routed drainage + WEIR mover, on a Voronoi mesh.

One small synthetic domain (400 m square, ~50 m Voronoi cells, 2 layers, 4 transient
periods) runs the production builders together in real MF6: marnage lakes with bank
seepage, a direct WEIR from the upper lake to the lower one, a WEIR outlet of the lower
lake moved into the SFR channel, drains routed to the network along the descent, and a
cutoff-style HFB wall. The test is written on the TARGET behavior of the stack (audit
2026-10-14). An assertion that fails only because a fix of another lot is not merged is
an ``xfail(strict=True)`` named after the finding, never a wider tolerance.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.solver.modflow6.builders import build_lak_package_args
from hydromodpy.solver.modflow6.builders.flow_barrier import build_flow_barrier_hfb
from hydromodpy.solver.modflow6.builders.mvr import build_mvr_period_records, mover_package_count
from hydromodpy.solver.modflow6.builders.sfr import (
    build_drainage_mover_records,
    build_sfr_package_args,
    remove_drain_cells,
    resolve_sfr_networks,
    sfr_drain_cells_to_drop,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.flow_adapter_helpers import worst_percent_discrepancy
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.geographic.core.sfr_network import SfrReachRow, SfrReachTrace
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec
from tests._helpers.mf6_ground import leave_ground_beside
from tests._helpers.tolerances import tol

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
_SIDE = 400.0
_NAME = "twolakevor"
_NLAY = 2
_INVERT = 106.5  # sill crest of the direct weir lac0 -> lac1
_SPILL = 98.5  # outlet invert of lac1, moved into the SFR channel
_BEDROCK = (70.0, 40.0)
_DRAIN_COUNT = 6

# tests/TOLERANCES.md row 44 (percent discrepancy of the GWF listing, as a fraction).
_BUDGET_CLOSURE_FRACTION = tol("sfr_standalone_budget_closure")


def _voronoi_cells():
    domain = box(0.0, 0.0, _SIDE, _SIDE)
    grid = RasterGridSpec(
        xmin=0.0, xmax=_SIDE, ymin=0.0, ymax=_SIDE, dx=_SIDE, dy=_SIDE, nrow=1, ncol=1,
        crs_wkt=_WKT,
    )  # fmt: skip
    request = MeshRequest(domain=domain, grid=grid, nominal_size_m=30.0, options={})
    return VoronoiMeshEngine().build(request)


def _ground(xy: np.ndarray) -> np.ndarray:
    # Valley along x = 320 (the stream); the land rises to the north and to the west.
    return 90.0 + 0.03 * xy[:, 1] + 0.03 * np.abs(xy[:, 0] - 320.0)


def _build_mesh() -> tuple[SolverMesh, dict[str, list[int]]]:
    cell_mesh = _voronoi_cells()
    probe = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.zeros(cell_mesh.n_cells),
        botm=np.zeros((_NLAY, cell_mesh.n_cells)),
        idomain=np.ones((_NLAY, cell_mesh.n_cells), dtype=int),
    )
    xy = np.asarray(probe.cell_centers(), dtype=float)
    ground = _ground(xy)
    centres = {"lac0": (120.0, 300.0), "lac1": (130.0, 120.0)}
    cells = {
        lake: [int(i) for i in np.flatnonzero(np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) < 55.0)]
        for lake, (cx, cy) in centres.items()
    }
    top = ground.copy()
    for ids in cells.values():
        top[ids] -= 3.0  # the carved bed
    botm = np.vstack([np.full(top.shape, _BEDROCK[0]), np.full(top.shape, _BEDROCK[1])])
    mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=top,
        botm=botm,
        idomain=np.ones((_NLAY, cell_mesh.n_cells), dtype=int),
    )
    return mesh, cells


def _trace() -> SfrReachTrace:
    head = LineString([(320.0, 380.0), (320.0, 200.0)])
    tail = LineString([(320.0, 200.0), (320.0, 10.0)])
    rows = (
        SfrReachRow(
            ifno=0, line=head, rlen=float(head.length), rtp=97.0, rgrd=1e-3, strahler=1,
            area_km2=1.0, upstream=(), downstream=(1,), is_terminal_to_lake=False,
        ),
        SfrReachRow(
            ifno=1, line=tail, rlen=float(tail.length), rtp=92.0, rgrd=1e-3, strahler=1,
            area_km2=2.0, upstream=(0,), downstream=(), is_terminal_to_lake=False,
        ),
    )  # fmt: skip
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def _model(mesh: SolverMesh) -> SimpleNamespace:
    bed = SimpleNamespace(dynamic_area=True, bank_seepage=True)
    abacus0 = [(101.0, 0.0, 7500.0), (111.0, 75000.0, 7500.0)]
    abacus1 = [(95.0, 0.0, 7500.0), (105.0, 75000.0, 7500.0)]
    lakes = {
        "lac0": {
            "polygon": None,
            "bedleak": 1e-7,
            "abacus": abacus0,
            "initial_stage": 108.0,
            "bed_reconstruction": bed,
            "outlets": [{"kind": "WEIR", "invert": _INVERT, "width": 20.0, "lakeout": 2}],
        },
        "lac1": {
            "polygon": None,
            "bedleak": 1e-7,
            "abacus": abacus1,
            "initial_stage": 99.5,
            "bed_reconstruction": bed,
            "outlets": [
                {
                    "kind": "WEIR",
                    "invert": _SPILL,
                    "width": 20.0,
                    "lakeout": 0,
                    "mover": {"reach": 1},
                }
            ],
        },
    }
    sfr = {
        "net0": {
            "width": {"kind": "constant", "value": 2.0},
            "reach_trace": _trace(),
            "headwater_inflow": {"kind": "constant", "value": 0.002, "units": "m3/s"},
            "runoff": {"kind": "constant", "value": 0.0005, "units": "m3/s"},
            "route_drainage": True,
        }
    }
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["lake", "sfr"], sinks_sources={"lakes": lakes, "sfr": sfr}),
        nper=4,
        perlen=np.full(4, 2 * 86400.0),
        steady=(False,) * 4,
        time_grid=None,
        time_units="seconds",
        model_output_name=_NAME,
    )


def _read_csv_rows(path: Path) -> list[dict[str, float]]:
    with open(path, encoding="utf-8") as fh:
        return [{k.upper(): float(v) for k, v in row.items()} for row in csv.DictReader(fh)]


@pytest.fixture(scope="module")
def stack(tmp_path_factory) -> SimpleNamespace:
    import flopy

    ws = tmp_path_factory.mktemp("two_lake_voronoi_stack")
    exe = str(ensure_solver_binary("mf6"))
    mesh, cells = _build_mesh()
    model = _model(mesh)

    wall = LineString([(40.0, 210.0), (260.0, 210.0)])
    hfb_rows = build_flow_barrier_hfb(mesh, line=wall, depths=[40.0], hydchr=1e-9)

    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    xy = np.asarray(mesh.cell_centers(), dtype=float)
    top = np.asarray(mesh.top, dtype=float)
    lake_set = {c for ids in cells.values() for c in ids}
    candidates = [
        int(i)
        for i in np.flatnonzero((xy[:, 0] > 230.0) & (xy[:, 0] < 290.0) & (xy[:, 1] > 120.0))
        if int(i) not in lake_set
    ][:_DRAIN_COUNT]
    drn_spd = {0: [[0, cid, float(top[cid]) - 0.5, 1e-4] for cid in candidates]}
    drn_spd = remove_drain_cells(drn_spd, cells=sfr_drain_cells_to_drop(networks))
    descent = build_solver_mesh_descent(
        mesh, lake_cells_by_lake={0: cells["lac0"], 1: cells["lac1"]}, base_level_mask=None
    )
    drainage_movers = build_drainage_mover_records(
        networks,
        drn_spd=drn_spd,
        receiver=descent.receiver,
        basin_cell_mask=np.ones(int(mesh.n_cells), dtype=bool),
        face_adjacency=mesh.face_adjacency(),
        mesh_top=top,
        lake_cells_by_number={0: list(cells["lac0"]), 1: list(cells["lac1"])},
    )

    lak_args = build_lak_package_args(model, solver_mesh=mesh, lake_cell_ids_by_lake=cells)
    assert lak_args is not None
    laktab_specs = lak_args.pop("laktab_specs")
    lake_movers = lak_args.pop("mover_records", [])
    for key in ("mover_maxpackages", "obs_continuous", "lake_obs_meta", "ts_specs"):
        lak_args.pop(key, None)
    lak_args.setdefault("perioddata", {0: [[0, "RAINFALL", 0.0], [1, "RAINFALL", 0.0]]})
    horizontal = [r for r in lak_args["connectiondata"] if r[3] == "HORIZONTAL"]

    sfr_args = build_sfr_package_args(
        model, networks=networks, external_mover=True, has_mover_records=False
    )
    assert sfr_args is not None
    sfr_obs = sfr_args.pop("obs_continuous")
    sfr_args.pop("sfr_obs_meta")
    sfr_args.pop("ts_specs", None)
    sfr_args.pop("mover_records", None)

    sim = flopy.mf6.MFSimulation(sim_name=_NAME, sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=4, perioddata=[(2 * 86400.0, 2, 1.2)] * 4)
    flopy.mf6.ModflowIms(
        sim,
        complexity="COMPLEX",
        linear_acceleration="BICGSTAB",
        outer_maximum=300,
        inner_maximum=300,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname=_NAME, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=mesh.nlay, idomain=mesh.idomain, **mesh.to_disv_kwargs(), length_units="METERS"
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-4, k33=1e-5, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    south = [[(1, int(i)), 90.0] for i in np.flatnonzero(xy[:, 1] < 30.0)]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: south})
    flopy.mf6.ModflowGwfdrn(
        gwf, pname="DRN", stress_period_data=drn_spd, save_flows=True, mover=bool(drainage_movers)
    )
    flopy.mf6.ModflowGwfhfb(gwf, stress_period_data={0: hfb_rows})

    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **lak_args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf, nrow=len(spec["table"]), ncol=3, table=spec["table"],
            filename=spec["filename"], parent_file=lak,
        )  # fmt: skip
    lak.obs.initialize(
        filename=f"{_NAME}.lak.obs",
        digits=10,
        print_input=False,
        continuous={
            f"{_NAME}.lak.obs.csv": [
                ("stageA", "STAGE", 1),
                ("stageB", "STAGE", 2),
                ("AtoB", "OUTLET", 1),
                ("Bsfr", "OUTLET", 2),
            ]
        },
    )
    sfr = flopy.mf6.ModflowGwfsfr(gwf, pname="SFR", **sfr_args)
    sfr.obs.initialize(
        filename=f"{_NAME}.sfr.obs", digits=10, print_input=False, continuous=sfr_obs
    )

    mvr_rows = build_mvr_period_records(drainage_movers) + list(lake_movers)
    packages = sorted({(str(r[0]),) for r in mvr_rows} | {(str(r[2]),) for r in mvr_rows})
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
        head_filerecord=f"{_NAME}.hds",
        budget_filerecord=f"{_NAME}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    leave_ground_beside(gwf)
    success, _ = sim.run_simulation(silent=True)
    listing = (ws / f"{_NAME}.lst").read_text(errors="replace")
    (ws / "hfb_rows.json").write_text(
        json.dumps([[list(r[0]), list(r[1]), r[2]] for r in hfb_rows])
    )
    return SimpleNamespace(
        ws=ws, mesh=mesh, cells=cells, success=success, listing=listing,
        hfb_rows=hfb_rows, horizontal=horizontal, drainage_movers=drainage_movers,
        lake_movers=lake_movers, n_cells=int(mesh.n_cells),
        lak=_read_csv_rows(ws / f"{_NAME}.lak.obs.csv"),
        sfr=_read_csv_rows(ws / f"{_NAME}.sfr.obs.csv"),
    )  # fmt: skip


pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.allow_subprocess,
]


def test_the_stack_is_really_assembled(stack) -> None:
    assert len(stack.cells["lac0"]) >= 2 and len(stack.cells["lac1"]) >= 2
    assert stack.hfb_rows, "the wall crosses no face"
    assert stack.drainage_movers, "no drain was routed to the network"
    assert stack.lake_movers, "the WEIR outlet carries no mover record"
    assert stack.horizontal, "marnage lakes carry no bank connection"


def test_every_period_converges(stack) -> None:
    assert stack.success, "MF6 returned failure"
    assert "FAILED TO MEET SOLVER CONVERGENCE" not in stack.listing


def test_the_budget_closes(stack) -> None:
    worst = worst_percent_discrepancy(stack.ws)
    assert worst is not None
    assert abs(worst) / 100.0 <= _BUDGET_CLOSURE_FRACTION


def test_the_weir_and_the_mover_carry_water(stack) -> None:
    last = stack.lak[-1]
    # lac0 starts above the sill (108 > 106.5): it spills into lac1 (negative = leaving lac0).
    assert stack.lak[0]["ATOB"] < 0.0
    assert last["STAGEA"] < 108.0
    # lac1 starts above its own outlet invert: the WEIR releases water through the mover
    # and the SFR channel receives it (FROM-MVR summed over the reaches).
    assert stack.lak[0]["BSFR"] < 0.0
    received = sum(v for k, v in stack.sfr[0].items() if k.endswith("_FROM_MVR"))
    assert received > 0.0


def test_the_wall_cuts_every_layer_of_each_crossed_face(stack) -> None:
    layers_by_face: dict[tuple[int, int], set[int]] = {}
    for (lay_a, ca), (lay_b, cb), _hyd in stack.hfb_rows:
        assert lay_a == lay_b
        layers_by_face.setdefault((min(ca, cb), max(ca, cb)), set()).add(int(lay_a))
    assert layers_by_face
    for face, layers in layers_by_face.items():
        assert layers == set(range(_NLAY)), f"face {face} is cut in layers {sorted(layers)} only"


def test_banks_sit_above_the_carved_bed(stack) -> None:
    top = np.asarray(stack.mesh.top, dtype=float)
    for lake_index, lake in enumerate(("lac0", "lac1")):
        bed = float(top[stack.cells[lake]].min())
        belevs = [r[5] for r in stack.horizontal if r[0] == lake_index]
        assert belevs, f"{lake} has no bank connection"
        assert min(belevs) >= bed - 1e-9, (
            f"{lake}: lowest bank belev {min(belevs):.2f} m under the bed {bed:.2f} m"
        )
