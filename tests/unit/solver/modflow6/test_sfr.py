"""The MF6 SFR package builder turns delineated river reaches into reaches on mesh cells.

Lengths are in m, streambed tops in m a.s.l., flows in m3/s and rainfall in m/s. A reach line is cut
at the cell boundaries, or shared among the cells of a river chain, then numbered from upstream to
downstream. The builder also couples terminal reaches to lakes through MVR records.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pandas as pd
import pytest
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import LineString

import hydromodpy.solver.modflow6.builders.sfr as sfr_module
from hydromodpy.catchment.algorithms.sfr_network import SfrReachRow, SfrReachTrace
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.mesh import registry
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import LineFamilySpec
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.forcing.dated_forcing import PiecewiseForcing
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.sfr import FlowReachConfig, FlowReachNetworkConfig
from hydromodpy.solver.modflow6.builders._sfr_network import chain_pieces, crossing_pieces
from hydromodpy.solver.modflow6.builders.lake_outflow import build_lake_mover_records
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord, build_mvr_period_records
from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    SfrReachRecord,
    build_drains,
    build_sfr,
    build_sfr_mover_records,
    build_sfr_obs_spec,
    build_sfr_package_args,
    build_sfr_period_data,
    remove_drain_cells,
    resolve_sfr_networks,
    sfr_drain_cells_to_drop,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, mesh_request
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

X0, Y0 = L93_ORIGIN
LENGTH_ATOL_M = 1e-9
LENGTH_RTOL = 1e-9
BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"
GMSH_ENGINES = [
    "regular",
    pytest.param(
        "triangle",
        marks=pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed"),
    ),
    pytest.param(
        "voronoi",
        marks=pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed"),
    ),
]

# Reach lines drawn in the unit square, rescaled to the bounds of each mesh.
UNIT_LINES = (
    LineString([(0.05, 0.93), (0.31, 0.62), (0.47, 0.55), (0.66, 0.31), (0.97, 0.08)]),
    LineString([(0.12, 0.1), (0.4, 0.42), (0.41, 0.8), (0.9, 0.86)]),
)

# A river made of two tributaries that join in a short stub, then a main stem.
WEST = LineString(
    [(X0 + 120, Y0 + 880), (X0 + 260, Y0 + 740), (X0 + 350, Y0 + 670), (X0 + 500, Y0 + 500)]
)
EAST = LineString(
    [(X0 + 880, Y0 + 820), (X0 + 720, Y0 + 700), (X0 + 590, Y0 + 620), (X0 + 500, Y0 + 500)]
)
STUB = LineString([(X0 + 500, Y0 + 500), (X0 + 512, Y0 + 486)])
MAIN = LineString(
    [(X0 + 512, Y0 + 486), (X0 + 540, Y0 + 380), (X0 + 650, Y0 + 250), (X0 + 780, Y0 + 70)]
)
CHAIN_REACHES = (  # (line, upstream, downstream)
    (WEST, (), (2,)),
    (EAST, (), (2,)),
    (STUB, (0, 1), (3,)),
    (MAIN, (2,), ()),
)

# Defaults the builder applies when the definition omits them.
STREAMBED_THICKNESS_M = 1.0
MIN_SLOPE = 1e-4


def regular_cell_mesh() -> PlanarCellMesh:
    mesh = solver_mesh_from_structured_arrays(
        nrow=30,
        ncol=40,
        top=np.zeros((30, 40)),
        botm=np.full((1, 30, 40), -10.0),
        dx=37.3,
        dy=41.7,
        xoff=350_000.37,
        yoff=6_780_000.11,
    )
    return mesh.cell_mesh


def cell_mesh_named(name: str) -> PlanarCellMesh:
    return {
        "regular": regular_cell_mesh,
        "triangles": lambda: bundle_triangles(BUNDLE),
        "dual": lambda: bundle_dual(BUNDLE),
    }[name]()


def lines_on(cell_mesh: PlanarCellMesh) -> list[LineString]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(line, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for line in UNIT_LINES
    ]


def gridintersect_reach(cell_mesh: PlanarCellMesh, line: LineString) -> list[tuple[int, float]]:
    """The split of the former builder, GridIntersect pieces ordered along the line."""
    n_cells = cell_mesh.n_cells
    disv = to_flopy_disv_args(cell_mesh.mesh, top=np.zeros(n_cells), botm=np.full((1, n_cells), -1))
    grid = VertexGrid(
        vertices=disv["vertices"],
        cell2d=disv["cell2d"],
        top=np.zeros(n_cells),
        botm=np.full((1, n_cells), -1.0),
        nlay=1,
        ncpl=n_cells,
        xoff=0.0,
        yoff=0.0,
    )
    pieces = []
    for row in GridIntersect(grid).intersect(line, geo_dataframe=False):
        length = float(row["lengths"])
        if length < 1e-6:
            continue
        middle = row["ixshapes"].interpolate(0.5, normalized=True)
        pieces.append((float(line.project(middle)), int(row["cellids"]), length))
    pieces.sort()
    return [(cell, length) for _, cell, length in pieces]


def river_chain_mesh(engine: str) -> PlanarCellMesh:
    river = LineString([*WEST.coords, *STUB.coords[1:], *MAIN.coords[1:]])
    return registry.mesh_engines.create(engine).build(
        mesh_request(
            grid_spec(40, 40, 25.0, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
            nominal_size_m=50.0,
            lines=(LineFamilySpec("rivers", "cell", (river, EAST)),),
        )
    )


def chain_cells(cell_mesh: PlanarCellMesh) -> set[int]:
    return {int(c) for chain in cell_mesh.chains("rivers") for c in chain.cell_ids}


def river_chain_model() -> SimpleNamespace:
    rows = tuple(
        SfrReachRow(
            ifno=ifno,
            line=line,
            rlen=float(line.length),
            rtp=90.0,
            rgrd=1e-3,
            strahler=1,
            area_km2=1.0,
            upstream=upstream,
            downstream=downstream,
            is_terminal_to_lake=False,
        )
        for ifno, (line, upstream, downstream) in enumerate(CHAIN_REACHES)
    )
    payload = {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": SfrReachTrace(reaches=rows, crs_wkt=LAMBERT93_WKT),
    }
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)),
            sfr={"net": payload},
        )
    )


def strip_mesh(nrow: int = 5, ncol: int = 5, nlay: int = 1) -> SolverMesh:
    top = np.full((nrow, ncol), 100.0)
    botm = np.stack([np.full((nrow, ncol), 100.0 - 50.0 * (k + 1)) for k in range(nlay)])
    return solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=botm, dx=10.0, dy=10.0
    )


def two_cell_mesh(*, up_bottom: float, down_bottom: float) -> SolverMesh:
    # One row of two cells, cell2d 0 upstream and cell2d 1 downstream.
    top = np.full((1, 2), 100.0)
    botm = np.array([[[up_bottom, down_bottom]]], dtype=float)  # (nlay=1, nrow=1, ncol=2)
    return solver_mesh_from_structured_arrays(nrow=1, ncol=2, top=top, botm=botm, dx=10.0, dy=10.0)


def reach_row(
    ifno: int,
    line: LineString,
    *,
    rtp: float,
    rgrd: float = 1e-3,
    strahler: int = 1,
    area_km2: float = 1.0,
    upstream: tuple[int, ...] = (),
    downstream: tuple[int, ...] = (),
    terminal: bool = False,
    terminal_lake: int | None = None,
) -> SfrReachRow:
    return SfrReachRow(
        ifno=ifno,
        line=line,
        rlen=float(line.length),
        rtp=rtp,
        rgrd=rgrd,
        strahler=strahler,
        area_km2=area_km2,
        upstream=upstream,
        downstream=downstream,
        is_terminal_to_lake=terminal,
        terminal_lake=terminal_lake,
    )


def fake_model(payloads: dict | None = None, nper: int = 1, perlen: tuple[float, ...] = (86400.0,)):
    sfr = {} if payloads is None else {"sfr": payloads}
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)), **sfr
        ),
        nper=nper,
        perlen=np.asarray(perlen, dtype=float),
        steady=(False,) * nper,
        time_grid=None,
        time_units="seconds",
        model_output_name="sfrtest",
    )


def trace_payload(trace: SfrReachTrace, **overrides) -> dict:
    return {"width": {"kind": "constant", "value": 2.0}, "reach_trace": trace} | overrides


def two_reach_trace() -> SfrReachTrace:
    # Reach 0 (headwater) runs diagonally across several cells, reach 1 continues to the grid
    # edge and is flagged terminal-to-lake.
    head = LineString([(2.0, 48.0), (25.0, 25.0)])
    tail = LineString([(25.0, 25.0), (48.0, 3.0)])
    rows = (
        reach_row(0, head, rtp=95.0, downstream=(1,)),
        reach_row(1, tail, rtp=94.0, upstream=(0,), terminal=True),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def west_east_trace(**row_kwargs) -> SfrReachTrace:
    # A straight line along the top row, cells 0..4 from west to east.
    line = LineString([(5.0, 45.0), (45.0, 45.0)])
    return SfrReachTrace(reaches=(reach_row(0, line, rtp=95.0, **row_kwargs),), crs_wkt="")


def two_terminal_two_lake_trace() -> SfrReachTrace:
    # The west stream drains into lake 2 (the pre-retenue), the east one into lake 1.
    west = LineString([(5.0, 45.0), (20.0, 45.0)])
    east = LineString([(30.0, 45.0), (45.0, 45.0)])
    rows = (
        reach_row(0, west, rtp=95.0, terminal=True, terminal_lake=2),
        reach_row(1, east, rtp=95.0, terminal=True, terminal_lake=1),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def explicit_payload(reaches: list[FlowReachConfig], **overrides) -> FlowReachNetworkConfig:
    return FlowReachNetworkConfig(reaches=reaches, **overrides)


def chain_reach(
    row: int, col: int, upstream: list[int], downstream: list[int], top: float, **extra
):
    return FlowReachConfig(
        cell={"kind": "cell", "cell": [0, row, col]},
        length="10 m",
        width="2 m",
        slope=1e-3,
        top=top,
        upstream=upstream,
        downstream=downstream,
        **extra,
    )


def two_reach_network(*, rtp_up: float, rtp_down: float) -> ResolvedSfrNetwork:
    up = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_up,
        upstream=(),
        downstream=(1,),
        is_headwater=True,
    )
    down = SfrReachRecord(
        ifno=1,
        cellid=(0, 1),
        rlen=10.0,
        rwid=2.0,
        rgrd=1e-3,
        rtp=rtp_down,
        upstream=(0,),
        downstream=(),
    )
    return ResolvedSfrNetwork(network_id="net0", reaches=(up, down), definition={})


def lone_reach(ifno: int, cell2d: int, *, terminal_lake: int | None) -> SfrReachRecord:
    return SfrReachRecord(
        ifno=ifno,
        cellid=(0, cell2d),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=terminal_lake is not None,
        terminal_lake=terminal_lake,
    )


def flagged_plus_bare(
    bare_xy: tuple[float, float],
    lake1_xy: tuple[float, float] = (0.0, 0.0),
    lake0_xy: tuple[float, float] = (10_000.0, 0.0),
) -> tuple[dict, np.ndarray]:
    """A shoreline reach flagged for lake 1 and a dead-end reach with no flag.

    Cell 5 holds the dead end, cell 6 is a lake 1 cell and cell 10 a lake 0 cell.
    """
    network = ResolvedSfrNetwork(
        network_id="net0",
        reaches=(lone_reach(0, 0, terminal_lake=1), lone_reach(1, 5, terminal_lake=None)),
        definition={"outflow_to_lake": 1},
    )
    centroids = np.zeros((11, 2), dtype=float)
    centroids[5] = bare_xy
    centroids[6] = lake1_xy
    centroids[10] = lake0_xy
    return {"net0": network}, centroids


# Without river chains, a reach is shared among the cells it crosses, as GridIntersect shared it.
# The two are compared on a regular grid at a non-integer origin, on the triangles and on the
# Voronoi dual of a committed bundle. Same cells in the same order, lengths within 1e-9 m.


@pytest.mark.parametrize("name", ["regular", "triangles", "dual"])
def test_pieces_are_those_of_gridintersect(name: str) -> None:
    cell_mesh = cell_mesh_named(name)
    for line in lines_on(cell_mesh):
        expected = gridintersect_reach(cell_mesh, line)
        pieces = crossing_pieces(cell_mesh, line)
        assert [piece.cell for piece in pieces] == [cell for cell, _ in expected]
        np.testing.assert_allclose(
            [piece.length for piece in pieces],
            [length for _, length in expected],
            rtol=0.0,
            atol=LENGTH_ATOL_M,
        )
        assert sum(piece.length for piece in pieces) == pytest.approx(line.length, rel=1e-12)


# On a mesh that carries a ``rivers`` cell family, each reach is shared among the chain cells
# nearest to it, cut halfway between the projections of consecutive centers.


@pytest.mark.parametrize("engine", GMSH_ENGINES)
def test_chain_pieces_keep_the_reach_length(engine: str) -> None:
    cell_mesh = river_chain_mesh(engine)
    lines = [line for line, _, _ in CHAIN_REACHES]
    pieces = chain_pieces(cell_mesh, lines, family="rivers")
    chain = chain_cells(cell_mesh)
    for line, shares in zip(lines, pieces, strict=True):
        assert shares, "every reach, the stub included, holds at least one cell"
        assert sum(s.length for s in shares) == pytest.approx(line.length, rel=LENGTH_RTOL)
        assert {s.cell for s in shares} <= chain
        middles = [s.middle for s in shares]
        assert middles == sorted(middles)
        assert all(s.length > 0.0 for s in shares)


@pytest.mark.parametrize("engine", GMSH_ENGINES)
def test_network_routes_downstream_on_chain_cells(engine: str) -> None:
    cell_mesh = river_chain_mesh(engine)
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 100.0),
        botm=np.full((1, n_cells), 50.0),
        idomain=np.ones((1, n_cells), dtype=int),
    )
    network = resolve_sfr_networks(river_chain_model(), solver_mesh=solver_mesh)["net"]
    assert network.downstream_increasing
    assert {r.cellid[1] for r in network.reaches} <= chain_cells(cell_mesh)
    total = sum(r.rlen for r in network.reaches)
    assert total == pytest.approx(sum(line.length for line, _, _ in CHAIN_REACHES), rel=LENGTH_RTOL)
    outlets = [r for r in network.reaches if not r.downstream]
    assert len(outlets) == 1


def test_trace_split_is_ordered_and_downstream_increasing() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace())})
    network = resolve_sfr_networks(model, solver_mesh=strip_mesh())["net0"]
    reaches = network.reaches

    # The two diagonal lines cross several cells each, so the split happened.
    assert len(reaches) > 2
    assert [reach.ifno for reach in reaches] == list(range(len(reaches)))
    assert network.downstream_increasing
    by_ifno = {reach.ifno: reach for reach in reaches}
    for reach in reaches:
        for down in reach.downstream:
            assert reach.ifno in by_ifno[down].upstream

    # The split conserves the polyline length.
    total = sum(reach.rlen for reach in reaches)
    expected = sum(row.line.length for row in two_reach_trace().reaches)
    assert total == pytest.approx(expected, rel=1e-6)

    # Headwater and terminal flags land on the first and the last reach.
    assert by_ifno[0].is_headwater
    assert by_ifno[len(reaches) - 1].is_terminal_to_lake
    assert not by_ifno[len(reaches) - 1].downstream

    # Streambed tops descend along every connection.
    for reach in reaches:
        for down in reach.downstream:
            assert by_ifno[down].rtp < reach.rtp

    # Every reach sits on a cell of the single layer.
    assert all(reach.cellid is not None and reach.cellid[0] == 0 for reach in reaches)


def test_trace_split_follows_the_line() -> None:
    model = fake_model({"net0": trace_payload(west_east_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    cells = [reach.cellid[1] for reach in networks["net0"].reaches]
    # Row 0 is the north row, so the top row (y in [40, 50]) is cells 0..4 west to east.
    assert cells == sorted(cells)
    assert len(cells) in (4, 5)


def test_unconnected_network_has_no_cell() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace(), connected_to_aquifer=False)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    assert all(reach.cellid is None for reach in networks["net0"].reaches)
    args = build_sfr_package_args(model, networks=networks)
    assert all(row[1] == (-1, -1) for row in args["packagedata"])


def test_packagedata_layout_and_connection_signs() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    args = build_sfr_package_args(model, networks=networks)

    assert args["nreaches"] == len(networks["net0"].reaches)
    assert args["maximum_picard_iterations"] == 1
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0
    for row in args["packagedata"]:
        # [ifno, cellid, rlen, rwid, rgrd, rtp, rbth, rhk, man, ncon, ustrf, ndv]
        assert len(row) == 12
        assert isinstance(row[1], tuple) and len(row[1]) == 2
        assert row[2] > 0.0 and row[3] > 0.0 and row[4] > 0.0
        assert row[6] > 0.0  # rbth
        assert row[8] > 0.0  # manning
        assert row[10] == pytest.approx(1.0)  # ustrf
        assert row[11] == 0  # ndv

    by_ifno = {reach.ifno: reach for reach in networks["net0"].reaches}
    for row in args["connectiondata"]:
        ups = [c for c in row[1:] if c >= 0]
        downs = [-c for c in row[1:] if c < 0]
        assert tuple(sorted(ups)) == by_ifno[row[0]].upstream
        assert tuple(sorted(downs)) == by_ifno[row[0]].downstream


WIDTH_LAWS = [
    pytest.param({"kind": "constant", "value": 3.5}, 3.5, id="constant"),
    pytest.param({"kind": "by_order", "widths": {1: 1.0, 2: 2.5}}, 2.5, id="by order"),
    pytest.param({"kind": "power_law", "coef": 2.0, "exp": 0.5}, 2.0 * 4.0**0.5, id="power law"),
]


@pytest.mark.parametrize(("width_cfg", "width_m"), WIDTH_LAWS)
def test_width_laws(width_cfg: dict, width_m: float) -> None:
    # One reach of Strahler order 2 draining 4 km2.
    trace = west_east_trace(strahler=2, area_km2=4.0)
    model = fake_model({"net0": trace_payload(trace, width=width_cfg)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    assert all(reach.rwid == pytest.approx(width_m) for reach in networks["net0"].reaches)


def test_explicit_network_resolves_cells() -> None:
    payload = explicit_payload(
        [
            chain_reach(0, 1, [], [2], 96.0),
            chain_reach(1, 1, [1], [3], 95.9),
            chain_reach(2, 1, [2], [], 95.8),
        ],
        # A single Picard pass only when nothing moves water into the reaches.
        route_drainage=False,
    )
    model = fake_model({"net0": payload})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    assert [reach.cellid for reach in networks["net0"].reaches] == [(0, 1), (0, 6), (0, 11)]
    assert networks["net0"].downstream_increasing
    args = build_sfr_package_args(model, networks=networks)
    assert args["maximum_picard_iterations"] == 1


def test_declared_zero_ustrf_is_kept() -> None:
    # 0.0 is a legitimate declaration, for a reach fed entirely from elsewhere. It is also falsy,
    # and the sibling-sum validator only fires on a fork, so an `or` would hand this reach all of
    # the upstream flow with nothing to catch it.
    head = chain_reach(0, 1, [], [2], 96.0)
    tail = chain_reach(1, 1, [1], [], 95.9, ustrf=0.0)
    model = fake_model({"net0": explicit_payload([head, tail])})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    assert networks["net0"].reaches[1].ustrf == pytest.approx(0.0)


def test_period_data_shares_runoff_by_length() -> None:
    model = fake_model(
        {
            "net0": trace_payload(
                two_reach_trace(),
                headwater_inflow={"kind": "constant", "value": 0.05, "units": "m3/s"},
                runoff={"kind": "constant", "value": 0.02, "units": "m3/s"},
                rainfall={"kind": "constant", "value": 1e-8, "units": "m/s"},
            )
        }
    )
    network = resolve_sfr_networks(model, solver_mesh=strip_mesh())["net0"]
    rows, ts_series = build_sfr_period_data(model, network=network)
    assert ts_series == []
    period0 = rows[0]

    inflow_rows = [row for row in period0 if row[1] == "inflow"]
    assert len(inflow_rows) == 1
    assert inflow_rows[0][0] == 0  # the headwater reach
    assert inflow_rows[0][2] == pytest.approx(0.05)

    runoff_rows = {row[0]: row[2] for row in period0 if row[1] == "runoff"}
    assert set(runoff_rows) == {reach.ifno for reach in network.reaches}
    assert sum(runoff_rows.values()) == pytest.approx(0.02)
    total_length = sum(reach.rlen for reach in network.reaches)
    for reach in network.reaches:
        assert runoff_rows[reach.ifno] == pytest.approx(0.02 * reach.rlen / total_length)

    rainfall_rows = [row for row in period0 if row[1] == "rainfall"]
    assert len(rainfall_rows) == len(network.reaches)
    assert all(row[2] == pytest.approx(1e-8) for row in rainfall_rows)


def test_drains_under_reaches_are_dropped() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    cells = sfr_drain_cells_to_drop(networks)
    assert cells
    drn_spd = {0: [[0, cid, 100.0, 0.05] for cid in range(25)]}
    filtered = remove_drain_cells(drn_spd, cells=cells)
    assert {int(row[1]) for row in filtered[0]} == set(range(25)) - cells


def test_reach_stops_at_a_lake_cell() -> None:
    # Once the DEM is hydro-conditioned, a stream routes through a lake. The reach is cut at the
    # lake footprint and the last dry reach is flagged terminal-to-lake, tagged with that lake.
    mesh = strip_mesh()
    model = fake_model({"net0": trace_payload(west_east_trace(), outflow_to_lake=1)})
    base = [r.cellid[1] for r in resolve_sfr_networks(model, solver_mesh=mesh)["net0"].reaches]
    lake_cell = base[-1]  # the downstream-most cell becomes a lake cell
    cut = resolve_sfr_networks(model, solver_mesh=mesh, lake_cells_by_number={0: [lake_cell]})
    cells = [r.cellid[1] for r in cut["net0"].reaches if r.cellid is not None]
    assert lake_cell not in cells
    assert len(cells) == len(base) - 1
    terminals = [r for r in cut["net0"].reaches if r.is_terminal_to_lake]
    assert len(terminals) == 1
    assert terminals[0].cellid[1] == base[-2]  # the last dry cell is the shoreline
    assert terminals[0].terminal_lake == 1  # 0-based lake 0 becomes the 1-based tag


def test_dead_end_goes_to_the_nearest_lake_cell() -> None:
    # A flagged shoreline tributary plus an unflagged dead end, the main stem stopping short of
    # the flat forebay. The dead end hands its flow to the nearest lake cell, not to EXT-OUTFLOW.
    nets, centroids = flagged_plus_bare((5.0, 0.0), lake1_xy=(6.0, 0.0), lake0_xy=(100.0, 0.0))
    records = build_sfr_mover_records(
        nets, lake_cells_by_number={0: [10], 1: [6]}, cell_centroids=centroids
    )
    by_provider = {r.provider_id: r for r in records}
    assert by_provider[0].receiver_id == 0  # flagged terminal_lake=1 gives 0-based lake 0
    assert by_provider[1].receiver == "LAK"
    assert by_provider[1].receiver_id == 1  # nearest lake cell 6 is lake 1


# A dead end is not fed to a lake when it is more than 300 m from the shore, or when it is
# the below-dam discharge reach next to the model outlet.
DEAD_ENDS = [
    pytest.param((400.0, 0.0), None, False, id="far from the shore"),
    pytest.param((50.0, 0.0), None, True, id="near the shore"),
    pytest.param((50.0, 0.0), (60.0, 0.0), False, id="at the model outlet"),
]


@pytest.mark.parametrize(("bare_xy", "outlet_xy", "is_fed"), DEAD_ENDS)
def test_dead_end_is_fed_to_a_lake(bare_xy, outlet_xy, is_fed) -> None:
    nets, centroids = flagged_plus_bare(bare_xy)
    records = build_sfr_mover_records(
        nets, lake_cells_by_number={0: [10], 1: [6]}, cell_centroids=centroids, outlet_xy=outlet_xy
    )
    assert any(r.provider_id == 1 for r in records) == is_fed


def test_unrouted_dead_end_is_reported(caplog) -> None:
    # Measured on the Cheze reservoir, the main stem stopped 1015 m short of the shoreline, just
    # past the 300 m snap, and 51 % of the network outflow left the model with no message.
    nets, centroids = flagged_plus_bare((400.0, 0.0))
    with caplog.at_level("WARNING"):
        build_sfr_mover_records(
            nets, lake_cells_by_number={0: [10], 1: [6]}, cell_centroids=centroids
        )
    assert "leaves the model by EXT-OUTFLOW instead of" in caplog.text
    assert "400 m from the shore" in caplog.text
    assert "lake_feeder_snap" in caplog.text


def test_routed_dead_end_is_not_reported(caplog) -> None:
    nets, centroids = flagged_plus_bare((50.0, 0.0))
    with caplog.at_level("WARNING"):
        build_sfr_mover_records(
            nets, lake_cells_by_number={0: [10], 1: [6]}, cell_centroids=centroids
        )
    assert "stop short of every shoreline" not in caplog.text


def test_terminal_at_the_outlet_is_not_fed() -> None:
    # A flagged terminal at the model outlet is the below-dam discharge reach. It leaves the
    # model whatever its streambed elevation.
    network = ResolvedSfrNetwork(
        network_id="net0",
        reaches=(lone_reach(0, 0, terminal_lake=1),),
        definition={"outflow_to_lake": 1},
    )
    centroids = np.zeros((2, 2), dtype=float)
    records = build_sfr_mover_records(
        {"net0": network},
        lake_cells_by_number={0: [1]},
        cell_centroids=centroids,
        outlet_xy=(5.0, 0.0),  # 5 m from the terminal, inside the keepout
    )
    assert all(r.provider_id != 0 for r in records)


def test_terminal_reach_feeds_the_lake() -> None:
    model = fake_model(
        {"net0": trace_payload(two_reach_trace(), outflow_to_lake=1, outflow_value=1.0)}
    )
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    records = build_sfr_mover_records(networks)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, MoverRecord)
    assert record.provider == "SFR"
    assert record.receiver == "LAK"
    assert record.receiver_id == 0
    assert record.provider_id == max(reach.ifno for reach in networks["net0"].reaches)
    # The records themselves are routed in build.py. The package only needs the flag.
    args = build_sfr_package_args(model, networks=networks, has_mover_records=bool(records))
    assert args["mover"] is True


def test_each_terminal_feeds_its_own_lake() -> None:
    # outflow_to_lake = 1 is only the fallback. Each terminal routes to the lake it drains into,
    # so the two terminals reach lakes 1 and 2 (receiver ids 0 and 1), not both lake 1.
    model = fake_model({"net0": trace_payload(two_terminal_two_lake_trace(), outflow_to_lake=1)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    records = build_sfr_mover_records(networks)
    assert len(records) == 2
    assert all(r.receiver == "LAK" for r in records)
    assert sorted(r.receiver_id for r in records) == [0, 1]


def test_obs_spec_covers_each_reach_and_mover() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace(), outflow_to_lake=1)})
    network = resolve_sfr_networks(model, solver_mesh=strip_mesh())["net0"]
    obs_continuous, meta = build_sfr_obs_spec(stem="m", network=network, has_mover=True)
    obslist = obs_continuous["m.sfr.obs.csv"]
    names = {entry[0] for entry in obslist}
    for reach in network.reaches:
        for quantity in ("stage", "depth", "downstream_flow", "ext_inflow", "ext_outflow"):
            assert f"r{reach.ifno}_{quantity}" in names
        assert f"r{reach.ifno}_gw_exchange" in names
        assert f"r{reach.ifno}_to_mvr" in names
    assert meta["reach_count"] == len(network.reaches)
    assert meta["obs_csv"] == "m.sfr.obs.csv"
    assert all(entry["network_id"] == "net0" for entry in meta["entries"])
    # 0-based integer ids only, flopy chokes on boundname obs ids.
    assert all(isinstance(entry[2], tuple) and isinstance(entry[2][0], int) for entry in obslist)


def test_inactive_sfr_returns_no_network() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace())})
    model.inputs = replace(
        model.inputs, boundaries=BoundaryConditionBundle(conditions={}, active_ids=("drainage",))
    )
    assert resolve_sfr_networks(model, solver_mesh=strip_mesh()) == {}
    assert build_sfr_package_args(model, networks={}) is None


# SFR and LAK are coupled through MVR records, never through an import.

MOVER_OUTLETS = [
    pytest.param(
        [
            {
                "kind": "WEIR",
                "invert": 95.0,
                "width": 5.0,
                "lakeout": 0,
                "mover": {"reach": 3, "mvrtype": "FACTOR", "value": 1.0},
            }
        ],
        [["LAK", 0, "SFR", 2, "FACTOR", 1.0]],
        id="spillway release, receiver is reach - 1",
    ),
    pytest.param(
        [
            {"kind": "WEIR", "invert": 95.0, "width": 5.0, "lakeout": 0},
            {
                "kind": "SPECIFIED",
                "lakeout": 0,
                "mover": {"reach": 1, "mvrtype": "UPTO", "value": 0.5},
            },
        ],
        # An outlet without a mover still advances the outlet counter.
        [["LAK", 1, "SFR", 0, "UPTO", 0.5]],
        id="outlet numbering counts outlets without mover",
    ),
]


@pytest.mark.parametrize(("outlets", "records"), MOVER_OUTLETS)
def test_lake_outlet_mover_to_sfr(outlets: list[dict], records: list[list]) -> None:
    lakes = {"lac0": {"outlets": outlets}}
    assert build_mvr_period_records(build_lake_mover_records(None, lakes=lakes)) == records


def test_mover_to_reach_zero_is_refused() -> None:
    outlet = {"kind": "WEIR", "invert": 95.0, "width": 5.0, "lakeout": 0, "mover": {"reach": 0}}
    with pytest.raises(ValueError, match="reach"):
        build_lake_mover_records(None, lakes={"lac0": {"outlets": [outlet]}})


def test_sfr_builder_never_imports_the_lake_builder() -> None:
    tree = ast.parse(Path(sfr_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("builders.lake" in name for name in imported)


def test_route_drainage_lifts_the_picard_cap() -> None:
    # One Picard pass assumes nothing moves water into the reaches. With route_drainage the
    # DRN to SFR mover inflow changes at each outer iteration and one pass would not converge.
    source = inspect.getsource(build_sfr_package_args)
    assert 'args["maximum_picard_iterations"] = 1' in source
    line = next(
        line for line in source.splitlines() if "downstream_increasing" in line and "if " in line
    )
    assert "route_drainage" in line


# The cell-bottom floor lifts a reach's streambed top so its bed stays inside the aquifer cell.
# A lake-enforced routing DEM can give a downstream reach a much higher cell bottom than its
# upstream neighbor. The builder floors every reach, then lifts upstream reaches from the outlet
# so that both the floor and the downhill order hold.

BED_FLOORS = [
    pytest.param(
        65.0,
        # Floor of the downstream bed, 65 + 1 + 0.1. The upstream bed sits one slope drop above.
        66.1,
        66.1 + MIN_SLOPE * 0.5 * (10.0 + 10.0),
        id="floor lifts the downstream reach",
    ),
    pytest.param(40.0, 59.9, 60.0, id="floor does not fire"),
]


@pytest.mark.parametrize(("down_bottom", "rtp_down", "rtp_up"), BED_FLOORS)
def test_floor_keeps_the_downhill_order(down_bottom: float, rtp_down: float, rtp_up: float) -> None:
    mesh = two_cell_mesh(up_bottom=40.0, down_bottom=down_bottom)
    network = two_reach_network(rtp_up=60.0, rtp_down=59.9)
    args = build_sfr_package_args(fake_model(), networks={"net0": network}, solver_mesh=mesh)

    # The network descends, so the single Picard pass is on.
    assert args["maximum_picard_iterations"] == 1
    # PACKAGEDATA row layout: [ifno, cellid, rlen, rwid, rgrd, rtp, rbth, ...].
    rtp = {int(row[0]): float(row[5]) for row in args["packagedata"]}
    assert rtp[1] == pytest.approx(rtp_down)
    assert rtp[0] == pytest.approx(rtp_up)
    assert rtp[0] > rtp[1]
    # Both beds stay above their own cell bottom.
    assert rtp[0] - STREAMBED_THICKNESS_M >= 40.0
    assert rtp[1] - STREAMBED_THICKNESS_M >= down_bottom


NETWORK_REFUSALS = [
    pytest.param(
        [chain_reach(0, 1, [2], [], 95.8), chain_reach(1, 1, [], [1], 96.0)],
        "downstream",
        id="downstream to the first reach",
    ),
    pytest.param(
        [
            chain_reach(0, 1, [], [2], 96.0),
            chain_reach(1, 1, [], [], 95.9),  # misses upstream=[1]
        ],
        "reciprocal",
        id="links not reciprocal",
    ),
    pytest.param(
        [
            chain_reach(0, 1, [], [2, 3], 96.0),
            chain_reach(1, 0, [1], [], 95.9, ustrf=0.6),
            chain_reach(1, 2, [1], [], 95.9, ustrf=0.6),
        ],
        "ustrf",
        id="sibling ustrf do not sum to one",
    ),
]


@pytest.mark.parametrize(("reaches", "message"), NETWORK_REFUSALS)
def test_explicit_network_refusals(reaches: list[FlowReachConfig], message: str) -> None:
    model = fake_model({"net0": explicit_payload(reaches)})
    with pytest.raises(ValueError, match=message):
        resolve_sfr_networks(model, solver_mesh=strip_mesh())


def test_multiple_networks_are_refused() -> None:
    model = fake_model(
        {"a": trace_payload(two_reach_trace()), "b": trace_payload(two_reach_trace())}
    )
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    with pytest.raises(ValueError, match="one SFR network"):
        build_sfr_package_args(model, networks=networks)


# A network that leaves the model by itself has no mover. A terminal reach flagged for a lake
# without any receiver is skipped with a warning, an unflagged network with one outlet and an
# outflow_to_lake sends that outlet to the lake.


def test_standalone_network_has_no_mover() -> None:
    model = fake_model({"net0": trace_payload(west_east_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    assert build_sfr_mover_records(networks) == []


def test_terminal_without_receiver_is_skipped(caplog) -> None:
    model = fake_model({"net0": trace_payload(west_east_trace(terminal=True))})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    with caplog.at_level("WARNING"):
        assert build_sfr_mover_records(networks) == []
    assert "feeds a lake but no receiver is set" in caplog.text


def test_single_outlet_feeds_the_lake() -> None:
    model = fake_model({"net0": trace_payload(west_east_trace(), outflow_to_lake=2)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    (record,) = build_sfr_mover_records(networks)
    # The line crosses cells 0 to 4, so reach 4 is the outlet. The lake number counts from 1 and
    # the receiver id from 0.
    assert (record.provider_id, record.receiver, record.receiver_id) == (4, "LAK", 1)


def test_two_outlets_cannot_feed_one_lake() -> None:
    west = LineString([(5.0, 45.0), (20.0, 45.0)])
    east = LineString([(30.0, 45.0), (45.0, 45.0)])
    trace = SfrReachTrace(
        reaches=(reach_row(0, west, rtp=95.0), reach_row(1, east, rtp=95.0)), crs_wkt=""
    )
    model = fake_model({"net0": trace_payload(trace, outflow_to_lake=1)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    with pytest.raises(ValueError, match="2 network outlets and no terminal-to-lake flag"):
        build_sfr_mover_records(networks)


# A diversion splits the flow of one reach into a reach downstream of it. Reach numbers count
# from 1 in the configuration and from 0 in the package.


def chain_of_three(**network) -> dict:
    reaches = [
        chain_reach(0, 1, [], [2], 96.0),
        chain_reach(1, 1, [1], [3], 95.9),
        chain_reach(2, 1, [2], [], 95.8),
    ]
    return {"net0": explicit_payload(reaches, **network)}


def diversion(**members) -> dict:
    return {"reach": 1, "to_reach": 2, "cprior": "FRACTION"} | members


def test_diversion_rows() -> None:
    constant = {"kind": "constant", "value": 86400.0, "units": "m3/day"}  # 1 m3/s
    diversions = [
        diversion(divflow={"kind": "constant", "value": 0.3}),
        diversion(to_reach=2, cprior="UPTO", divflow=constant),
        diversion(reach=2, to_reach=3, cprior=None) | {"cprior": "FRACTION"},
    ]
    model = fake_model(chain_of_three(diversions=diversions))
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    args = build_sfr_package_args(model, networks=networks)
    # DIVERSIONS rows are [reach, index on that reach, target reach, rule], all 0-based.
    assert args["diversions"] == [[0, 0, 1, "FRACTION"], [0, 1, 1, "UPTO"], [1, 0, 2, "FRACTION"]]
    assert [row[-1] for row in args["packagedata"]] == [2, 1, 0]  # ndv of each reach
    rows = [row for row in args["perioddata"][0] if row[1] == "diversion"]
    assert rows == [[0, "diversion", 0, 0.3], [0, "diversion", 1, pytest.approx(1.0)]]


DIVERSION_REFUSALS = [
    pytest.param(
        trace_payload(two_reach_trace(), diversions=[diversion()]),
        "requires the explicit reaches table",
        id="reach trace network",
    ),
    pytest.param(
        chain_of_three(diversions=[diversion(to_reach=9)])["net0"],
        r"diversions\[0\] reach ids are outside the network",
        id="target outside the network",
    ),
    pytest.param(
        chain_of_three(diversions=[diversion(to_reach=3)])["net0"],
        r"to_reach 3 is not a downstream connection of reach 1",
        id="target not downstream",
    ),
    pytest.param(
        chain_of_three(
            diversions=[diversion(divflow={"kind": "csv", "path_file": "q.csv"})],
        )["net0"],
        "divflow must be a constant forcing",
        id="divflow series",
    ),
]


@pytest.mark.parametrize(("payload", "message"), DIVERSION_REFUSALS)
def test_diversion_refusals(payload, message) -> None:
    model = fake_model({"net0": payload})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    with pytest.raises(ValueError, match=message):
        build_sfr_package_args(model, networks=networks)


def test_payload_without_reaches_is_refused() -> None:
    model = fake_model({"net0": {"width": {"kind": "constant", "value": 2.0}}})
    with pytest.raises(ValueError, match="neither an explicit reaches table nor a bound"):
        resolve_sfr_networks(model, solver_mesh=strip_mesh())


def test_zero_streambed_thickness_is_refused() -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace(), streambed_thickness=0.0)})
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    with pytest.raises(ValueError, match="streambed_thickness must be > 0"):
        build_sfr_package_args(model, networks=networks)


# The package is built on a flopy model of the mesh, after the lakes and before the movers.


def gwf_on(mesh: SolverMesh, tmp_path: Path, nper: int = 1):
    sim = flopy.mf6.MFSimulation(sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=nper, perioddata=[(86400.0, 1, 1.0)] * nper)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="sfrtest")
    n_cells = mesh.cell_mesh.n_cells
    flopy.mf6.ModflowGwfdisv(
        gwf, **to_flopy_disv_args(mesh.cell_mesh.mesh, top=mesh.top, botm=np.asarray(mesh.botm))
    )
    assert n_cells == 25
    return gwf


def test_sfr_package_is_built(tmp_path) -> None:
    mesh = strip_mesh()
    model = fake_model({"net0": trace_payload(two_reach_trace(), outflow_to_lake=1)})
    model.gwf = gwf_on(mesh, tmp_path)
    model.full_path = tmp_path
    model.lak = object()
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    records = build_sfr_mover_records(networks)
    mover_rows: list = []
    build_sfr(model, mesh, networks, records, mover_rows, n_lakes_built=1)
    assert model.sfr.packagedata.get_data().shape[0] == len(networks["net0"].reaches)
    assert (tmp_path / "sfrtest.sfr.meta.json").is_file()
    # One row [provider, id, receiver, id, type, value] from the last of the 8 reaches to lake 1.
    assert mover_rows == [["SFR", 7, "LAK", 0, "FACTOR", 1.0]]


MOVER_REFUSALS = [
    pytest.param(
        SimpleNamespace(lak=None), 1, "declares outflow_to_lake but no lake is active", id="no lake"
    ),
    pytest.param(
        SimpleNamespace(lak=object()),
        0,
        r"outflow_to_lake=1 has no matching lake \(0 lakes",
        id="lake not built",
    ),
]


@pytest.mark.parametrize(("model", "n_lakes", "message"), MOVER_REFUSALS)
def test_sfr_mover_refusals(model, n_lakes, message) -> None:
    record = MoverRecord("SFR", 1, "LAK", 0, "FACTOR", 1.0)
    with pytest.raises(ValueError, match=message):
        build_sfr(model, strip_mesh(), {"net0": object()}, [record], [], n_lakes)


# The hillslope drain sits on every open cell. The cells under a reach and the lake bed cells lose
# theirs, and with route_drainage each drain whose descent ends on a reach moves its water to it.


def drain_model(mesh: SolverMesh, tmp_path: Path, **members) -> SimpleNamespace:
    n_cells = mesh.cell_mesh.n_cells
    drainage = SimpleNamespace(value=1e-4, units="m2/s")  # conductance of one cell
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(
                conditions={"drainage": drainage}, active_ids=("drainage",)
            )
        ),
        nper=1,
        ncpl=n_cells,
        dem_mask=mesh.closed_surface(),
        hk=np.full((1, n_cells), 1e-5),
        sink_fill=False,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
        gwf=gwf_on(mesh, tmp_path),
        **members,
    )


def east_descent() -> SimpleNamespace:
    # Every cell drains to its east neighbour, the last column leaves the model.
    receiver = np.arange(1, 26)
    receiver[4::5] = -1
    return SimpleNamespace(stopping_receiver=receiver, without_adjacency=lambda: "descent")


def test_drains_around_a_reach(tmp_path) -> None:
    mesh = strip_mesh()
    model = drain_model(mesh, tmp_path, _marnage_lake_cells={1: [24, 23]})
    model_networks = resolve_sfr_networks(fake_model(chain_of_three()), solver_mesh=mesh)
    basin = SimpleNamespace(is_catchment=True, mask=np.ones(25, dtype=bool))
    rows = build_drains(
        model,
        mesh,
        np.zeros(25, bool),
        np.zeros(25, bool),
        model_networks,
        east_descent(),
        basin,
        {},
    )
    # Reach cells 1, 6 and 11 and the lake cells 23 and 24 lose their drain.
    assert model._drain_dropped_cells == {1, 6, 11, 23, 24}
    assert model.drn.stress_period_data.get_data()[0].shape[0] == 25 - 5
    assert model.descent == "descent"
    # Cells 0, 5 and 10 drain to the reach on their east side. Their rows are the 1st, 5th and
    # 9th of the DRN list once cell 1 is dropped, and the reaches are numbered 0 to 2.
    assert sorted((row[1], row[3]) for row in rows) == [(0, 0), (4, 1), (8, 2)]
    assert {(row[0], row[2]) for row in rows} == {("DRN", "SFR")}


def test_drains_without_a_reach(tmp_path) -> None:
    mesh = strip_mesh()
    model = drain_model(mesh, tmp_path)
    rows = build_drains(model, mesh, np.zeros(25, bool), np.zeros(25, bool), {}, None, None, {})
    assert rows == []
    assert model.drn.stress_period_data.get_data()[0].shape[0] == 25
    assert model.descent is None


def test_drain_routing_needs_a_descent(tmp_path) -> None:
    mesh = strip_mesh()
    model = drain_model(mesh, tmp_path)
    networks = resolve_sfr_networks(fake_model(chain_of_three()), solver_mesh=mesh)
    with pytest.raises(ValueError, match="walks the descent D, and this build has none"):
        build_drains(
            model, mesh, np.zeros(25, bool), np.zeros(25, bool), networks, east_descent(), None, {}
        )


def test_drain_routing_without_outlet_warns(tmp_path, caplog) -> None:
    mesh = strip_mesh()
    model = drain_model(mesh, tmp_path)
    networks = resolve_sfr_networks(fake_model(chain_of_three()), solver_mesh=mesh)
    basin = SimpleNamespace(is_catchment=False, mask=np.ones(25, dtype=bool))
    with caplog.at_level("WARNING"):
        build_drains(
            model, mesh, np.zeros(25, bool), np.zeros(25, bool), networks, east_descent(), basin, {}
        )
    assert "no outlet and no watershed polygon" in caplog.text


def monthly_model(payloads: dict) -> SimpleNamespace:
    """Two monthly periods, January and February 2003, with their calendar."""
    model = fake_model(payloads, nper=2, perlen=(31 * 86400.0, 28 * 86400.0))
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    time = ModelTime(
        grid=SimpleNamespace(window=window), regime="transient", first_period_steady=True
    )
    model.inputs = replace(model.inputs, time=time)
    return model


def test_monthly_runoff_is_a_time_series(tmp_path) -> None:
    segments = [
        {
            "start": "2003-01-01",
            "end": "2003-02-01",
            "forcing": {"kind": "constant", "value": 0.01},
        },
        {"start": "2003-02-01", "forcing": {"kind": "constant", "value": 0.03}},
    ]
    runoff = PiecewiseForcing(segments=segments, units="m3/s")
    model = monthly_model({"net0": trace_payload(west_east_trace(), runoff=runoff)})
    model.modflow_config = SimpleNamespace(
        process_specific=SimpleNamespace(lak_forcing_mode="ts6", ts6_min_periods=1)
    )
    mesh = strip_mesh()
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    args = build_sfr_package_args(model, networks=networks)
    # The line crosses 5 cells (5, 10, 10, 10 and 5 m), so each reach gets its own series, scaled
    # by its share of the 40 m of river.
    by_name = {series.name: series.values for series in args["ts_specs"]}
    rows = args["perioddata"][0]
    assert [row[1] for row in rows] == ["runoff"] * 5
    lengths = np.array([reach.rlen for reach in networks["net0"].reaches])
    for row, length in zip(rows, lengths, strict=True):
        assert len(by_name[row[2]]) == 3  # the series repeats the February value at the end
        np.testing.assert_allclose(
            by_name[row[2]][:2], np.array([0.01, 0.03]) * length / lengths.sum(), rtol=1e-9
        )


STEMS = [
    pytest.param("run1", "", "run1", id="output name"),
    pytest.param(None, "abc", "abc", id="model name"),
    pytest.param(None, None, "model", id="no name"),
]


@pytest.mark.parametrize(("output_name", "model_name", "stem"), STEMS)
def test_observation_file_stem(output_name, model_name, stem) -> None:
    model = fake_model({"net0": trace_payload(two_reach_trace())})
    model.model_output_name = output_name
    model.model_name = model_name
    networks = resolve_sfr_networks(model, solver_mesh=strip_mesh())
    args = build_sfr_package_args(model, networks=networks)
    assert list(args["obs_continuous"]) == [f"{stem}.sfr.obs.csv"]


def test_sfr_time_series_file(tmp_path) -> None:
    segments = [
        {
            "start": "2003-01-01",
            "end": "2003-02-01",
            "forcing": {"kind": "constant", "value": 0.01},
        },
        {"start": "2003-02-01", "forcing": {"kind": "constant", "value": 0.03}},
    ]
    runoff = PiecewiseForcing(segments=segments, units="m3/s")
    model = monthly_model({"net0": trace_payload(west_east_trace(), runoff=runoff)})
    model.modflow_config = SimpleNamespace(
        process_specific=SimpleNamespace(lak_forcing_mode="ts6", ts6_min_periods=1)
    )
    mesh = strip_mesh()
    model.gwf = gwf_on(mesh, tmp_path, nper=2)
    model.full_path = tmp_path
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    build_sfr(model, mesh, networks, [], [], n_lakes_built=0)
    model.gwf.simulation.write_simulation(silent=True)
    assert "TS6" in (tmp_path / "sfrtest.sfr").read_text().upper()
    text = (tmp_path / "sfrtest.sfr.ts").read_text()
    table = text.split("BEGIN timeseries")[1].split("END timeseries")[0].split("\n")
    rows = np.array([[float(w) for w in line.split()] for line in table if line.strip()])
    # Reaches of 5, 10, 10, 10 and 5 m share the January runoff of 0.01 m3/s by length (40 m),
    # and 0.03 m3/s in February. The last row repeats February at the end of the run.
    shares = np.array([5.0, 10.0, 10.0, 10.0, 5.0]) / 40.0
    np.testing.assert_allclose(rows[:, 1:], np.outer([0.01, 0.03, 0.03], shares), rtol=1e-9)
