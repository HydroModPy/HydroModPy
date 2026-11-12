"""The length of a river line shared among the cells of a mesh, in order along it."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.sfr_network import SfrReachRow, SfrReachTrace
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders._sfr_network import (
    MIN_PIECE_LENGTH_M,
    _reach_pieces,
    _reach_width,
    chain_pieces,
    crossing_pieces,
)
from hydromodpy.solver.modflow6.builders.sfr import resolve_sfr_networks
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.bundle_cell_meshes import bundle_triangles
from tests._helpers.mesh_cases import regular_mesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

GRID = regular_mesh(3, 4, dx=10.0)
"""Four columns and three rows of 10 m cells on [0, 40] x [0, 30], row 0 north."""

MIDDLE_ROW = np.array([4, 5, 6, 7])


def _with_river(cells: np.ndarray):
    return dataclasses.replace(GRID, cell_chains=(CellChain("rivers", 0, cells),))


def test_a_line_along_the_chain_shares_its_length_among_its_cells() -> None:
    line = LineString([(0.0, 15.0), (40.0, 15.0)])

    [pieces] = chain_pieces(_with_river(MIDDLE_ROW), [line], family="rivers")

    assert [piece.cell for piece in pieces] == MIDDLE_ROW.tolist()
    assert sum(piece.length for piece in pieces) == pytest.approx(line.length)
    assert [piece.middle for piece in pieces] == pytest.approx([5.0, 15.0, 25.0, 35.0])


def test_a_mesh_without_chains_or_without_lines_gives_no_piece() -> None:
    line = LineString([(0.0, 15.0), (40.0, 15.0)])

    assert chain_pieces(GRID, [line], family="rivers") == [[]]
    assert chain_pieces(_with_river(MIDDLE_ROW), [], family="rivers") == []


def test_a_line_farther_than_a_cell_size_from_every_chain_cell_gets_no_piece() -> None:
    near = LineString([(0.0, 15.0), (40.0, 15.0)])
    far = LineString([(0.0, 60.0), (40.0, 60.0)])

    pieces = chain_pieces(_with_river(MIDDLE_ROW), [near, far], family="rivers")

    assert len(pieces[0]) == 4
    assert pieces[1] == []


def test_a_line_shorter_than_the_smallest_share_stays_in_one_piece() -> None:
    stub = LineString([(14.0, 15.0), (14.0 + 0.5 * MIN_PIECE_LENGTH_M, 15.0)])

    [pieces] = chain_pieces(_with_river(MIDDLE_ROW), [stub], family="rivers")

    assert len(pieces) == 1
    assert pieces[0].length == pytest.approx(stub.length)


def test_without_chains_each_cell_gets_the_length_of_the_line_inside_it() -> None:
    line = LineString([(5.0, 15.0), (35.0, 15.0)])

    pieces = crossing_pieces(GRID, line)

    assert [piece.cell for piece in pieces] == MIDDLE_ROW.tolist()
    assert [piece.length for piece in pieces] == pytest.approx([5.0, 10.0, 10.0, 5.0])


def test_a_line_off_the_mesh_crosses_no_cell() -> None:
    assert crossing_pieces(GRID, LineString([(50.0, 0.0), (60.0, 10.0)])) == []


def test_a_line_that_grazes_a_corner_leaves_that_cell_out() -> None:
    # Within a micrometer of the node (20, 10), the diagonal cuts a sliver off cell 6.
    graze = 0.5 * MIN_PIECE_LENGTH_M
    line = LineString([(10.0 + graze, 0.0), (30.0 + graze, 20.0)])

    pieces = crossing_pieces(GRID, line)

    assert sum(piece.length for piece in pieces) == pytest.approx(line.length, abs=1e-5)
    assert all(piece.length >= MIN_PIECE_LENGTH_M for piece in pieces)


WIDTH_CASES = [
    pytest.param(
        {"kind": "by_order", "widths": {1: 2.0, 3: 6.0}}, 5, 6.0, id="above the widest order"
    ),
    pytest.param({"kind": "by_order", "widths": {1: 2.0, 3: 6.0}}, 2, 2.0, id="between two orders"),
    pytest.param(
        {"kind": "by_order", "widths": {2: 4.0, 3: 6.0}}, 1, 4.0, id="below the narrowest"
    ),
]


@pytest.mark.parametrize(("width_cfg", "strahler", "width_m"), WIDTH_CASES)
def test_width_of_an_order_outside_the_declared_ones(width_cfg, strahler, width_m) -> None:
    assert _reach_width(width_cfg, strahler=strahler, area_km2=1.0, location="net") == width_m


WIDTH_REFUSALS = [
    pytest.param(
        {"kind": "constant"}, "constant law requires a value", id="constant without value"
    ),
    pytest.param({"kind": "by_order", "widths": {}}, "requires a widths mapping", id="no widths"),
    pytest.param({"kind": "by_order"}, "requires a widths mapping", id="widths missing"),
    pytest.param(
        {"kind": "cube"}, "must be constant, by_order or power_law; got cube", id="unknown law"
    ),
]


@pytest.mark.parametrize(("width_cfg", "match"), WIDTH_REFUSALS)
def test_width_refusals(width_cfg, match) -> None:
    with pytest.raises(ValueError, match=match):
        _reach_width(width_cfg, strahler=1, area_km2=1.0, location="net")


# Five 10 m cells on one row, cells 0 to 4 from west to east, the reaches on the northern row.
STRIP = solver_mesh_from_structured_arrays(
    nrow=5, ncol=5, top=np.full((5, 5), 100.0), botm=np.full((1, 5, 5), 50.0), dx=10.0, dy=10.0
)
CELL_BOUNDS_M = [(5.0, 15.0), (25.0, 45.0)]  # reach 0 over cells 0 and 1, reach 1 over cells 2 to 4


def reach_row(ifno: int, x_from: float, x_to: float, **links) -> SfrReachRow:
    line = LineString([(x_from, 45.0), (x_to, 45.0)])
    return SfrReachRow(
        ifno=ifno,
        line=line,
        rlen=float(line.length),
        rtp=95.0,
        rgrd=1e-3,
        strahler=1,
        area_km2=1.0,
        upstream=links.get("upstream", ()),
        downstream=links.get("downstream", ()),
        is_terminal_to_lake=False,
        terminal_lake=None,
    )


def trace_model(rows: tuple[SfrReachRow, ...]) -> SimpleNamespace:
    payload = {"width": {"kind": "constant", "value": 2.0}, "reach_trace": SfrReachTrace(rows, "")}
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)),
            sfr={"net0": payload},
        )
    )


def two_reaches_in_line() -> SimpleNamespace:
    (a_from, a_to), (b_from, b_to) = CELL_BOUNDS_M
    return trace_model(
        (
            reach_row(0, a_from, a_to, downstream=(1,)),
            reach_row(1, b_from, b_to, upstream=(0,)),
        )
    )


def test_a_reach_inside_a_lake_makes_its_upstream_neighbour_the_shoreline() -> None:
    # Reach 1 lies on cells 2 to 4, all lake cells, so nothing of it stays. Reach 0 ends on the shore.
    networks = resolve_sfr_networks(
        two_reaches_in_line(), solver_mesh=STRIP, lake_cells_by_number={1: [2, 3, 4]}
    )

    reaches = networks["net0"].reaches

    assert [reach.cellid[1] for reach in reaches] == [0, 1]
    assert [reach.is_terminal_to_lake for reach in reaches] == [False, True]
    assert reaches[-1].terminal_lake == 2  # lake number 1 (0-based) is the 2nd lake


def test_a_reach_over_an_inactive_cell_is_kept_without_a_cell(caplog) -> None:
    inactive = np.zeros((1, 25), dtype=bool)
    inactive[0, 1] = True
    mesh = solver_mesh_from_structured_arrays(
        nrow=5,
        ncol=5,
        top=np.full((5, 5), 100.0),
        botm=np.full((1, 5, 5), 50.0),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )

    networks = resolve_sfr_networks(two_reaches_in_line(), solver_mesh=mesh)

    reaches = networks["net0"].reaches
    assert [reach.cellid is None for reach in reaches] == [False, True, False, False, False]
    assert "crosses inactive cell 1" in caplog.text


def test_an_empty_trace_is_refused() -> None:
    with pytest.raises(ValueError, match="reach_trace holds no reach"):
        resolve_sfr_networks(trace_model(()), solver_mesh=STRIP)


def test_reaches_that_feed_each_other_are_refused() -> None:
    (a_from, a_to), (b_from, b_to) = CELL_BOUNDS_M
    cycle = trace_model(
        (
            reach_row(0, a_from, a_to, upstream=(1,), downstream=(1,)),
            reach_row(1, b_from, b_to, upstream=(0,), downstream=(0,)),
        )
    )

    with pytest.raises(ValueError, match="has a cycle"):
        resolve_sfr_networks(cycle, solver_mesh=STRIP)


def test_reach_off_the_mesh_is_refused() -> None:
    off = SimpleNamespace(ifno=3, line=LineString([(60.0, 0.0), (70.0, 10.0)]))
    on_chain = SimpleNamespace(cell_mesh=_with_river(MIDDLE_ROW))
    no_chain = SimpleNamespace(cell_mesh=GRID)

    with pytest.raises(ValueError, match="does not intersect any grid cell"):
        _reach_pieces(no_chain, [off], location="net")
    with pytest.raises(ValueError, match="reach 3 runs off the river cells"):
        _reach_pieces(on_chain, [off], location="net")


def explicit_reach(row: int = 0, col: int = 1, **overrides) -> dict:
    reach = {
        "cell": {"kind": "cell", "cell": [0, row, col]},
        "length": 10.0,
        "width": 2.0,
        "slope": 1e-3,
        "top": 96.0,
        "upstream": [],
        "downstream": [],
    }
    return reach | overrides


def explicit_model(*reaches: dict, **definition) -> SimpleNamespace:
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)),
            sfr={"net0": {"reaches": list(reaches)} | definition},
        )
    )


def triangle_solver_mesh() -> SolverMesh:
    cell_mesh = bundle_triangles("stream_depletion_glover_balmer_tri_refined_well")
    n_cells = cell_mesh.n_cells
    return SolverMesh(
        cell_mesh=cell_mesh,
        top=np.zeros(n_cells),
        botm=np.full((1, n_cells), -10.0),
        idomain=np.ones((1, n_cells), dtype=int),
    )


def strip_with_dry_cell(cell: int) -> SolverMesh:
    inactive = np.zeros((1, 25), dtype=bool)
    inactive[0, cell] = True
    return solver_mesh_from_structured_arrays(
        nrow=5,
        ncol=5,
        top=np.full((5, 5), 100.0),
        botm=np.full((1, 5, 5), 50.0),
        dx=10.0,
        dy=10.0,
        inactive_mask=inactive,
    )


EXPLICIT_REFUSALS = [
    pytest.param(
        [explicit_reach(upstream=[5])],
        STRIP,
        "upstream id 5 is outside the network",
        id="id outside",
    ),
    pytest.param(
        [explicit_reach(cell={"kind": "xy", "cell": [0, 0, 1]})],
        STRIP,
        "supports the cell-based location",
        id="location by coordinates",
    ),
    pytest.param(
        [explicit_reach()],
        triangle_solver_mesh(),
        "needs a structured grid",
        id="unstructured grid",
    ),
    pytest.param(
        [explicit_reach(row=9, col=9)],
        STRIP,
        r"outside the grid \(25 cells\)",
        id="beyond the grid",
    ),
    pytest.param(
        [explicit_reach(row=0, col=2)],
        strip_with_dry_cell(2),
        "is inactive",
        id="inactive cell",
    ),
    pytest.param(
        [explicit_reach(downstream=[]), explicit_reach(row=1, upstream=[1])],
        STRIP,
        "is fed by reach 0 which does not list it downstream",
        id="fed by a reach that does not feed it",
    ),
]


@pytest.mark.parametrize(("reaches", "mesh", "match"), EXPLICIT_REFUSALS)
def test_explicit_network_refusals(reaches, mesh, match) -> None:
    with pytest.raises(ValueError, match=match):
        resolve_sfr_networks(explicit_model(*reaches), solver_mesh=mesh)


def test_explicit_reaches_off_the_aquifer_have_no_cell() -> None:
    model = explicit_model(explicit_reach(), connected_to_aquifer=False)

    reaches = resolve_sfr_networks(model, solver_mesh=STRIP)["net0"].reaches

    assert [reach.cellid for reach in reaches] == [None]
