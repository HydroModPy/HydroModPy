"""Stage restart of lakes and reaches (m a.s.l.) from a prior run or a spin-up cycle.

The last stage of each lake is read from the run, stored in the Zarr restart group and used
as the LAK start stage. Reaches under SFR storage do the same from the binary stage file.
Stages are written to the package with all their digits.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.catchment.algorithms.sfr_network import SfrReachRow, SfrReachTrace
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import HeadRule, PriorState, SolvedState
from hydromodpy.results.storage.prior_state import read_restart_lake_stages
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.builders.lake import (
    apply_lake_stages,
    build_lak_package_args,
    read_final_lake_stages,
)
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.builders.sfr import (
    _initial_stages as initial_stages,
)
from hydromodpy.solver.modflow6.builders.sfr import (
    build_sfr_package_args,
    read_final_sfr_stages,
    resolve_sfr_networks,
)
from hydromodpy.solver.modflow6.extractors.lake import final_lake_stages
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_final_lake_stages() -> None:
    timeseries = [
        {"station_id": "lake:forebay", "variable": "stage", "timestep": 0, "value": 80.0},
        {"station_id": "lake:forebay", "variable": "stage", "timestep": 1, "value": 86.9},
        {"station_id": "lake:forebay", "variable": "volume", "timestep": 1, "value": 999.0},
        {"station_id": "lake:sill", "variable": "stage", "timestep": 0, "value": 74.0},
        # A non-lake station (e.g. a gauge) must never leak into the lake map.
        {"station_id": "gauge:x", "variable": "stage", "timestep": 5, "value": 1.0},
    ]
    assert final_lake_stages(timeseries) == {"forebay": 86.9, "sill": 74.0}


def test_restart_state_round_trip(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    sz.write_lake_restart_state({"forebay": 86.93, "sill": 74.15})
    sz.close()

    stages = read_restart_lake_stages(str(tmp_path / "sim.zarr"))
    assert stages == {"forebay": pytest.approx(86.93), "sill": pytest.approx(74.15)}


def test_empty_restart_state(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    sz.write_lake_restart_state({})
    sz.close()
    assert read_restart_lake_stages(str(tmp_path / "sim.zarr")) == {}


def lak_args(initial) -> dict:
    """The LAK arguments of two lakes, one of them with an ``initial_stage`` of 60 m."""
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(2)])
    mesh = solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    model = SimpleNamespace(
        model_output_name="restart_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            initial=initial,
            lakes={
                "lac0": {
                    "polygon": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                    "initial_stage": 60.0,
                    "outlets": [],
                },
                "lac1": {
                    "polygon": Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 9.0), (90.0, 360.0, 9.0)],
                    "initial_stage": 70.0,
                    "outlets": [],
                },
            },
        ),
    )
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    return args


def prior_with(stages):
    return PriorState(head=np.zeros((2, 16)), lake_stages=stages, path="prior.zarr")


def solved_with(stages):
    return SolvedState(head=np.zeros((2, 16)), solver="modflow6", lake_stages=stages)


STAGE_SOURCES = [
    pytest.param(prior_with, id="prior state of a restart_from"),
    pytest.param(solved_with, id="solved state of the cycle before"),
]


@pytest.mark.parametrize("source", STAGE_SOURCES)
def test_restart_stage_over_initial_stage(source) -> None:
    # lac1 is absent from the stages on purpose, as in a partial restart.
    args = lak_args(source({"lac0": 88.5}))

    strt_by_name = {row[3]: float(row[1]) for row in args["packagedata"]}
    assert strt_by_name["lac0"] == pytest.approx(88.5)  # restart wins over initial_stage 60
    assert strt_by_name["lac1"] == pytest.approx(70.0)  # absent from restart -> initial_stage kept


def test_restart_stage_digits() -> None:
    stage = 13.95991694769827

    args = lak_args(PriorState(head=np.zeros((2, 16)), lake_stages={"lac0": stage}, path="p"))

    (row,) = (row for row in args["packagedata"] if row[3] == "lac0")
    assert row[1] == "13.95991694769827"
    assert float(row[1]) == stage


def lak_package(tmp_path: Path, strt: float):
    """A written FloPy LAK package of two lakes, the stage of each given as a float."""
    sim = flopy.mf6.MFSimulation(sim_name="s", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    vertices = [[0, 0.0, 0.0], [1, 0.0, 10.0], [2, 10.0, 10.0], [3, 10.0, 0.0]]
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=2,
        nvert=4,
        top=20.0,
        botm=[0.0],
        vertices=vertices,
        cell2d=[[0, 5.0, 5.0, 4, 0, 1, 2, 3], [1, 5.0, 5.0, 4, 0, 1, 2, 3]],
    )
    return flopy.mf6.ModflowGwflak(
        gwf,
        nlakes=2,
        boundnames=True,
        packagedata=[[0, strt, 1, "lac0"], [1, strt + 1.0, 1, "lac1"]],
        connectiondata=[
            [0, 0, (0, 0), "vertical", 1e-3, 0.0, 0.0, 0.0, 0.0],
            [1, 0, (0, 1), "vertical", 1e-3, 0.0, 0.0, 0.0, 0.0],
        ],
    )


def test_cycle_stage_digits(tmp_path: Path) -> None:
    lak = lak_package(tmp_path, strt=60.0)

    apply_lake_stages(lak, {"lac1": 13.95991694769827})
    lak.write()

    rows = (
        (tmp_path / "m.lak").read_text().split("BEGIN packagedata")[1].split("END")[0].split("\n")
    )
    stages = {line.split()[3]: line.split()[1] for line in rows if line.strip()}
    assert stages == {"lac0": "60.00000000", "lac1": "13.95991694769827"}


def write_stage_file(path: Path, records: list[list[float]]) -> None:
    """Write a binary stage file as MODFLOW 6 does, one record per time step, in double."""
    header = np.dtype(
        [
            ("kstp", "i4"),
            ("kper", "i4"),
            ("pertim", "f8"),
            ("totim", "f8"),
            ("text", "S16"),
            ("ncol", "i4"),
            ("nrow", "i4"),
            ("ilay", "i4"),
        ]
    )
    with path.open("wb") as handle:
        for step, values in enumerate(records, start=1):
            np.array([(1, step, step, step, b"STAGE", len(values), 1, 1)], dtype=header).tofile(
                handle
            )
            np.array(values, dtype="f8").tofile(handle)


def test_stage_file_of_another_lake_count(tmp_path: Path) -> None:
    path = tmp_path / "m.lak.stage"
    write_stage_file(path, [[1.5, 2.5]])

    with pytest.raises(ValueError, match="holds 2 lake stage"):
        read_final_lake_stages(path, ["lac0"])


def test_missing_stage_file(tmp_path: Path) -> None:
    assert read_final_lake_stages(tmp_path / "none.lak.stage", ["lac0"]) is None
    assert read_final_sfr_stages(tmp_path / "none.sfr.stage") == {}


def test_final_reach_stages(tmp_path: Path) -> None:
    path = tmp_path / "m.sfr.stage"
    write_stage_file(path, [[9.0, 8.0, 7.0], [8.5, 7.5, 6.123456789012345]])

    assert read_final_sfr_stages(path) == {0: 8.5, 1: 7.5, 2: 6.123456789012345}


def initial_stages_of(initial, ifnos: tuple[int, ...]):
    model = SimpleNamespace(inputs=SimpleNamespace(initial=initial))
    reaches = [SimpleNamespace(ifno=ifno) for ifno in ifnos]
    return initial_stages(model, reaches, location="flow.sinks_sources.sfr.net")


def test_reach_stage_digits() -> None:
    prior = PriorState(
        head=np.zeros((1, 3)),
        lake_stages={},
        path="p",
        sfr_stages={1: 12.3456789012345678, 0: 13.0},
    )

    assert initial_stages_of(prior, (0, 1)) == [[0, "13.0"], [1, "12.345678901234567"]]


STAGELESS_STARTS = [
    pytest.param(PriorState(np.zeros((1, 3)), {}, "p"), id="prior state without stages"),
    pytest.param(HeadRule("top"), id="head rule"),
    pytest.param(SolvedState(head=np.zeros((1, 3)), solver="modflow6"), id="solved state"),
]


@pytest.mark.parametrize("initial", STAGELESS_STARTS)
def test_start_without_reach_stages(initial) -> None:
    assert initial_stages_of(initial, (0, 1)) == []


def test_reach_stages_of_another_network() -> None:
    prior = PriorState(np.zeros((1, 3)), {}, "p", sfr_stages={0: 1.0, 1: 2.0, 2: 3.0})

    with pytest.raises(ValueError, match="holds the stage of 3 reach"):
        initial_stages_of(prior, (0, 1))


def two_reach_network(storage: bool) -> dict:
    """Reach 0 crosses several cells, reach 1 continues to the grid edge and ends in a lake."""
    head = LineString([(2.0, 48.0), (25.0, 25.0)])
    tail = LineString([(25.0, 25.0), (48.0, 3.0)])

    def reach(ifno, line, rtp, **links):
        return SfrReachRow(
            ifno=ifno,
            line=line,
            rlen=float(line.length),
            rtp=rtp,
            rgrd=1e-3,
            strahler=1,
            area_km2=1.0,
            upstream=links.get("upstream", ()),
            downstream=links.get("downstream", ()),
            is_terminal_to_lake=links.get("terminal", False),
            terminal_lake=None,
        )

    trace = SfrReachTrace(
        reaches=(
            reach(0, head, 95.0, downstream=(1,)),
            reach(1, tail, 94.0, upstream=(0,), terminal=True),
        ),
        crs_wkt="EPSG:32630",
    )
    return {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": trace,
        "storage": storage,
    }


def sfr_args(storage: bool, initial=None) -> dict:
    """The SFR arguments of a two-reach network, with or without channel storage."""
    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)),
            sfr={"net0": two_reach_network(storage)},
        ),
        nper=1,
        perlen=np.asarray((86400.0,), dtype=float),
        steady=(False,),
        time_grid=None,
        time_units="seconds",
        model_output_name="sfrtest",
    )
    if initial is not None:
        model.inputs = replace(model.inputs, initial=initial)
    mesh = solver_mesh_from_structured_arrays(
        nrow=5,
        ncol=5,
        top=np.full((5, 5), 100.0),
        botm=np.full((1, 5, 5), 50.0),
        dx=10.0,
        dy=10.0,
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    args = build_sfr_package_args(model, networks=networks)
    assert args is not None
    return args


def test_sfr_storage_takes_prior_stages() -> None:
    first = sfr_args(storage=True)
    stages = {row[0]: 90.0 + row[0] / 3 for row in first["packagedata"]}
    prior = PriorState(np.zeros((1, 25)), {}, "p", sfr_stages=stages)

    args = sfr_args(storage=True, initial=prior)

    assert args["storage"] is True
    assert args["stage_filerecord"] == "sfrtest.sfr.stage"
    assert args["initialstages"] == [[ifno, repr(stage)] for ifno, stage in stages.items()]
