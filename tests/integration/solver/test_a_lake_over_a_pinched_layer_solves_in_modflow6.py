"""MODFLOW 6 solves a lake that sits over a column whose layer is pinched out.

The layers are built by surfaces and the thin cells become ``idomain = -1`` with
no thickness, the active cell next to them taking it. A lake takes the top layer
of its columns, and the LAK package leaks into the first active cell below. Four
stacks put a pass-through cell where the lake looks:

- ``cap``: the pinched layer is the top layer, so the lake sits on a pass-through
  cell where the layer is thin and on an active one where it is thick. Where it is
  thin the lake holds no water inside the stack and leaks through its bed only.
- ``below``: the pinched layer is the one under the lake, so the lake leaks
  through a pass-through cell into the layer under it.
- ``bank``: the ``cap`` stack with the lake on the thick columns, next to columns
  whose top layer is pinched, so the banks reach the active cell under them.
- ``shallow``: every layer under the lake is pinched, so no active cell is left
  under the lake. The lake mask refuses it.

The LAK package is the one ``build_lak_package_args`` assembles. MODFLOW 6
converges, the lake is never connected to a cell that is not active, each column
leaks into the first active cell under the lake, the lake exchanges water in the
pinched columns, and the budget of the model and of the lake closes (TOLERANCES.md
row 44, the listing discrepancy bound).
"""

from __future__ import annotations

import csv
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.layering import layer_stack
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow6.builders.lake import build_lak_package_args
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.support.computational_top import disv_grid_kwargs
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.listing import percent_discrepancies
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.tolerances import tol

pytestmark = [pytest.mark.mf6, pytest.mark.binary, pytest.mark.allow_subprocess]

_BUDGET_CLOSURE_FRACTION = tol("sfr_standalone_budget_closure")

NROW, NCOL = 5, 8
N_CELLS = NROW * NCOL
STEP = 100.0
RECHARGE_M_S = 2e-8
THIN_M = np.array([6.0, 5.0, 4.0, 3.0, 0.5, 0.5, 0.5, 0.5])
"""Thickness of the thin layer in each column: it is under the minimum from column 4 on."""
PINCHED_FROM = 4
LAKE_ROWS = (1, 2, 3)
STEM = "lake"


def _lake_cells(kind: str) -> list[int]:
    columns = (2, 3) if kind == "bank" else (3, 4)
    return [r * NCOL + c for r in LAKE_ROWS for c in columns]


def _pinched_cells(cells: list[int]) -> list[int]:
    return [c for c in cells if c % NCOL >= PINCHED_FROM]


def _thick_cells(cells: list[int]) -> list[int]:
    return [c for c in cells if c % NCOL < PINCHED_FROM]


def _layering(kind: str) -> VerticalGridConfig:
    if kind in ("cap", "bank"):
        layers = [
            {"name": "weathered", "surface": "thin_base", "min_thickness": 1.0},
            {"name": "fissured", "thickness": 20.0},
            {"name": "rock"},
        ]
    else:
        layers = [
            {"name": "cover", "thickness": 8.0},
            {"name": "weathered", "surface": "thin_base", "min_thickness": 1.0},
            {"name": "rock"},
        ]
    return VerticalGridConfig.model_validate({"genmtd_lay": "surfaces", "layer": layers})


def _stack(kind: str) -> SolverMesh:
    cols = np.arange(N_CELLS) % NCOL
    top = 100.0 - 1.0 * cols
    thin = THIN_M[cols]
    base = top - thin if kind in ("cap", "bank") else top - 8.0 - thin
    bottom = top - 60.0
    if kind == "shallow":
        lake = _lake_cells(kind)
        bottom[lake] = top[lake] - 8.5
    stack = layer_stack(
        top=top,
        bottom=bottom,
        invalid=np.zeros(N_CELLS, dtype=bool),
        vertical_config=_layering(kind),
        bases={"thin_base": base},
        nodata=-9999.0,
    )
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW, ncol=NCOL, top=top, botm=stack.botm, dx=STEP, dy=STEP
    )
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=stack.idomain)


def _lake_model(abacus: list[tuple[float, float, float]], stage: float) -> SimpleNamespace:
    lake = {"polygon": None, "bedleak": 1e-6, "abacus": abacus, "initial_stage": stage}
    return SimpleNamespace(
        model_output_name=STEM,
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={"lake": lake},
        ),
    )


def _connection_floor(rows: list[list], mesh: SolverMesh) -> float:
    """Lowest bottom MODFLOW 6 gives a connection: a vertical one bottoms at its cell top."""
    floors = []
    for row in rows:
        lay, cell = row[2]
        if row[3] == "VERTICAL":
            floors.append(float(mesh.top[cell]) if lay == 0 else float(mesh.botm[lay - 1, cell]))
        else:
            floors.append(float(row[5]))
    return min(floors)


def _lak_args(mesh: SolverMesh, lake_cells: list[int]) -> tuple[dict, float]:
    """Return the LAK package arguments of the lake and the floor of its connections.

    The abacus must start at that floor, which the connections give, so the package
    is assembled twice.
    """
    area = len(lake_cells) * STEP * STEP
    trial = _lake_model([(0.0, 0.0, area), (1.0, area, area)], 1.0)
    cells = {"lake": lake_cells}
    trial_args = build_lak_package_args(trial, solver_mesh=mesh, lake_cell_ids_by_lake=cells)
    floor = _connection_floor(trial_args["connectiondata"], mesh)
    abacus = [
        (floor, 0.0, area),
        (floor + 2.0, 2.0 * area, area),
        (floor + 12.0, 12.0 * area, area),
    ]
    args = build_lak_package_args(
        _lake_model(abacus, floor + 3.0), solver_mesh=mesh, lake_cell_ids_by_lake=cells
    )
    return args, floor


def _run(kind: str, ws) -> SimpleNamespace:
    import flopy

    pinched = _stack(kind)
    lake_cells = _lake_cells(kind)
    mesh = apply_lake_idomain_mask(
        pinched, lake_cell_ids_by_lake={"lake": lake_cells}, occupied_layers=1
    )
    args, floor = _lak_args(mesh, lake_cells)
    laktab_specs = args.pop("laktab_specs")
    obs_continuous = args.pop("obs_continuous")
    for key in ("lake_obs_meta", "ts_specs"):
        args.pop(key, None)
    args.setdefault("perioddata", {0: [[0, "RAINFALL", 0.0]]})

    sim = flopy.mf6.MFSimulation(
        sim_name=STEM, sim_ws=str(ws), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="COMPLEX",
        outer_dvclose=1e-6,
        inner_dvclose=1e-8,
        outer_maximum=300,
        inner_maximum=300,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname=STEM, save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf, **disv_grid_kwargs(SimpleNamespace(solver_mesh=mesh, open_water_cell_ids=[]))
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-5, k33=1e-6)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1e-5, steady_state={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=floor + 1.0)
    west = [c for c in range(N_CELLS) if c % NCOL == 0]
    east = [c for c in range(N_CELLS) if c % NCOL == NCOL - 1]
    chd = [
        [(k, c), head]
        for cells, head in ((west, 100.0), (east, 90.0))
        for k in range(mesh.nlay)
        for c in cells
        if int(mesh.idomain[k, c]) > 0
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    # The lake owns its surface: the build zeroes the recharge of its columns.
    rate = np.full(N_CELLS, RECHARGE_M_S)
    rate[lake_cells] = 0.0
    flopy.mf6.ModflowGwfrcha(
        gwf, recharge=rate, irch=np.maximum(mesh.top_active_layer(), 0), save_flows=True
    )
    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf,
            nrow=len(spec["table"]),
            ncol=3,
            table=spec["table"],
            filename=spec["filename"],
            parent_file=lak,
        )
    lak.obs.initialize(
        filename=f"{STEM}.lak.obs", digits=10, print_input=False, continuous=obs_continuous
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{STEM}.hds",
        budget_filerecord=f"{STEM}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    result = SimpleNamespace(
        ws=ws,
        kind=kind,
        lake_cells=lake_cells,
        pinched=pinched,
        mesh=mesh,
        rows=args["connectiondata"],
        floor=floor,
        success=success,
    )
    if success:
        head = np.asarray(flopy.utils.HeadFile(str(ws / f"{STEM}.hds")).get_data(), dtype=float)
        result.head = head.reshape(mesh.nlay, N_CELLS)
        with open(ws / f"{STEM}.lak.obs.csv", encoding="utf-8") as fh:
            result.obs = {k: float(v) for k, v in list(csv.DictReader(fh))[-1].items()}
    return result


_RUNS: dict[str, SimpleNamespace] = {}


def _solved(kind: str, tmp_path_factory) -> SimpleNamespace:
    """Run one stack once per module and share the result between fixtures."""
    if kind not in _RUNS:
        _RUNS[kind] = _run(kind, tmp_path_factory.mktemp(f"mf6_{kind}"))
    return _RUNS[kind]


@pytest.fixture(scope="module", params=["cap", "below", "bank"])
def solved(request, tmp_path_factory) -> SimpleNamespace:
    return _solved(request.param, tmp_path_factory)


@pytest.fixture(scope="module")
def cap(tmp_path_factory) -> SimpleNamespace:
    return _solved("cap", tmp_path_factory)


@pytest.fixture(scope="module")
def bank(tmp_path_factory) -> SimpleNamespace:
    return _solved("bank", tmp_path_factory)


def _flow(solved, row: list) -> float:
    """Lake to aquifer flow of one connection, from the LAK observations."""
    return solved.obs[f"LAKE_LAK_{solved.rows.index(row)}"]


def test_the_lake_sits_over_a_pass_through_cell(solved) -> None:
    idomain = solved.pinched.idomain
    lake = solved.lake_cells
    pinched_layer = 1 if solved.kind == "below" else 0
    if solved.kind == "bank":
        assert (idomain[0, lake] == 1).all()
        assert (idomain[0, [c + 1 for c in lake if c % NCOL == 3]] == -1).all()
        return
    assert (idomain[pinched_layer, _pinched_cells(lake)] == -1).all()
    assert (idomain[pinched_layer, _thick_cells(lake)] == 1).all()


def test_a_lake_with_no_active_cell_below_is_refused() -> None:
    pinched = _stack("shallow")
    lake = _lake_cells("shallow")
    assert (pinched.idomain[1:, lake] == -1).all()
    with pytest.raises(
        ValueError, match=r"leaves 6 column\(s\) with no active cell under the lake"
    ):
        apply_lake_idomain_mask(pinched, lake_cell_ids_by_lake={"lake": lake}, occupied_layers=1)


def test_modflow6_converges(solved) -> None:
    assert solved.success


def test_the_lake_connects_to_active_cells_only(solved) -> None:
    for row in solved.rows:
        lay, cell = row[2]
        assert int(solved.mesh.idomain[lay, cell]) > 0, row


def test_each_lake_column_leaks_into_the_first_active_cell_under_the_lake(solved) -> None:
    lake = solved.lake_cells
    vertical = {row[2][1]: row[2][0] for row in solved.rows if row[3] == "VERTICAL"}
    assert sorted(vertical) == sorted(lake)
    below = solved.mesh.idomain[1:, lake] > 0
    expected = dict(zip(lake, 1 + below.argmax(axis=0), strict=True))
    assert vertical == expected
    if solved.kind == "below":
        assert {vertical[c] for c in _pinched_cells(lake)} == {2}


def test_a_lake_column_over_a_pinched_cap_exchanges_through_its_bed(cap) -> None:
    solved = cap
    lake = solved.lake_cells
    vertical = {row[2][1]: row for row in solved.rows if row[3] == "VERTICAL"}
    for cell in _pinched_cells(lake):
        assert vertical[cell][2] == (1, cell)
        assert abs(_flow(solved, vertical[cell])) > 0.0
    # These cells border the pinched lake columns only, which hold no water band.
    beside = [
        c for c in range(N_CELLS) if c not in lake and c % NCOL in (PINCHED_FROM, PINCHED_FROM + 1)
    ]
    assert not [r for r in solved.rows if r[3] == "HORIZONTAL" and r[2][1] in beside]


def test_the_banks_reach_the_active_cell_under_a_pinched_neighbour(bank) -> None:
    solved = bank
    neighbours = {c + 1 for c in solved.lake_cells if c % NCOL == 3}
    banks = [row for row in solved.rows if row[3] == "HORIZONTAL" and row[2][1] in neighbours]
    assert {row[2] for row in banks} == {(1, c) for c in neighbours}
    for row in banks:
        cell = row[2][1]
        assert row[6] - row[5] > 0.0
        assert row[6] <= float(solved.mesh.top[cell])
        assert abs(_flow(solved, row)) > 0.0


def test_the_head_is_computed_in_the_active_cells_only(solved) -> None:
    computed = np.abs(solved.head) < 1e20
    np.testing.assert_array_equal(computed, solved.mesh.idomain > 0)


def test_the_lake_exchanges_water_with_the_aquifer_through_every_connection(solved) -> None:
    flows = np.array([solved.obs[f"LAKE_LAK_{i}"] for i in range(len(solved.rows))])
    assert (np.abs(flows) > 0.0).all()
    assert solved.obs["LAKE_STAGE"] > solved.floor


def test_the_budget_of_the_model_and_of_the_lake_closes(solved) -> None:
    discrepancies = percent_discrepancies(solved.ws)
    assert discrepancies
    assert max(abs(v) for v in discrepancies) <= 100.0 * _BUDGET_CLOSURE_FRACTION
