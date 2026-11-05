from __future__ import annotations

import ast
import inspect
import logging
from types import SimpleNamespace
from types import SimpleNamespace as NS

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow6.build import _resolve_spillway_receivers
from hydromodpy.solver.modflow6.builders import lake as lake_builder
from hydromodpy.solver.modflow6.builders.lake import resolve_spillway_seed_cells
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow_common import catchment_basin
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
)
from hydromodpy.solver.modflow_common.flow_directions import (
    DESCENT_EPSILON_M,
    build_solver_mesh_descent,
    resolve_dam_foot_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from hydromodpy.spatial.drainage import descent as core_descent
from hydromodpy.spatial.drainage.descent import DescentBasin
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.descent_cases import grid_descent
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.results.stream._heads_dam import (
    AXIS,
    CELL,
    DAM_FOOT_ROW,
    N_COLS,
    N_ROWS,
    cell,
    centre,
    dam_geometry,
    topography,
)

# The descent sidecar carries the basin of D; an older sidecar reads back without one.
#
# The extractors never see the model, so the basin reaches them through the
# sidecar with its outlet, rule, area and seeding. A sidecar written before the
# basin was stored reads back with ``basin`` None, so its readers fall back on
# their old support. A stored basin naming an unknown rule, or an outlet outside
# itself, is refused.

N = 6


def _descent():
    rows, cols = np.divmod(np.arange(N * N), N)
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=(10.0 + rows + cols).reshape(N, N), botm=np.full((1, N, N), -5.0)
    )
    return build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)


def _basin(outlet: int = 0, rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N * N, dtype=bool)
    mask[[0, 1, N]] = True
    return DescentBasin(mask=mask, outlet=outlet, rule=rule, area_m2=3.0, seeded_at_outlet=True)


def test_the_sidecar_round_trips_the_basin(tmp_path) -> None:
    basin = _basin()
    write_descent_sidecar(_descent(), tmp_path, "m", basin=basin)

    record = read_descent_sidecar(tmp_path / "m.descent.npz")

    assert record is not None
    np.testing.assert_array_equal(record.basin, basin.mask)
    assert (record.basin_outlet, record.basin_rule) == (0, "within_polygon")
    assert record.basin_area_m2 == 3.0
    assert record.basin_seeded_at_outlet is True


def test_a_sidecar_written_before_the_basin_reads_back_without_one(tmp_path) -> None:
    write_descent_sidecar(_descent(), tmp_path, "m")

    record = read_descent_sidecar(tmp_path / "m.descent.npz")

    assert record is not None
    assert record.basin is None
    assert record.basin_outlet == -1
    assert record.basin_rule == ""
    assert np.isnan(record.basin_area_m2)
    assert record.basin_seeded_at_outlet is False


@pytest.mark.parametrize(
    ("basin", "message"),
    [
        (_basin(rule="polygon_centroid"), "names basin rule 'polygon_centroid'"),
        (_basin(outlet=5), "basin outlet outside its basin"),
    ],
)
def test_a_stored_basin_that_does_not_hold_is_refused(tmp_path, basin, message) -> None:
    write_descent_sidecar(_descent(), tmp_path, "m", basin=basin)

    with pytest.raises(ValueError, match=message):
        read_descent_sidecar(tmp_path / "m.descent.npz")


def test_a_basin_without_its_fields_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "m", basin=_basin())
    assert path is not None
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "basin_rule"}
    np.savez(path, **kept)

    with pytest.raises(ValueError, match="holds a basin without basin_rule"):
        read_descent_sidecar(path)


# The lake and descent section of the MF6 build leaves D beside the model, dam feet included.
#
# ``run_pre_processing`` hands the section to ``_build_descent_and_dam_feet``: it
# builds D, resolves the toe cell of each declared spillway through the
# production path and writes the sidecar the extractor stores. A build that no
# longer calls it stores no D and no dam foot, and a calibration scores without
# forced heads, so both the call and the section are pinned.

LAKE_NROW, LAKE_NCOL = 5, 7


LAKE = {"res": [2 * LAKE_NCOL + 3, 2 * LAKE_NCOL + 4]}


TOE = 2 * LAKE_NCOL + 2  # west of the lake cell nearest the outlet, lower than its row neighbors


def _mesh() -> SolverMesh:
    _, cols = np.divmod(np.arange(LAKE_NROW * LAKE_NCOL), LAKE_NCOL)
    top = (10.0 + cols).reshape(LAKE_NROW, LAKE_NCOL)
    return solver_mesh_from_structured_arrays(
        nrow=LAKE_NROW,
        ncol=LAKE_NCOL,
        top=top,
        botm=np.full((1, LAKE_NROW, LAKE_NCOL), -50.0),
        dx=10.0,
        dy=10.0,
    )


def _model(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=[], sinks_sources={}),
        full_path=str(tmp_path),
        model_output_name="model",
        geographic=None,
    )


def _declare_spillway(monkeypatch, declared: bool) -> None:
    outlets = [{"mover": {"to_downstream_reach": True}}] if declared else []
    monkeypatch.setattr(
        lake_builder, "_active_lake_definitions", lambda model: {"res": {"outlets": outlets}}
    )


def _build(model, outlet_xy=(0.0, 25.0)):
    return build._build_descent_and_dam_feet(
        model, _mesh(), LAKE, np.zeros(LAKE_NROW * LAKE_NCOL, dtype=bool), outlet_xy
    )


def test_the_build_calls_the_section_that_writes_the_sidecar() -> None:
    tree = ast.parse(inspect.getsource(build.run_pre_processing))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_build_descent_and_dam_feet" in called


def test_the_section_writes_the_sidecar_with_the_dam_feet(monkeypatch, tmp_path) -> None:
    _declare_spillway(monkeypatch, declared=True)
    model = _model(tmp_path)

    descent, _, seeds = _build(model)

    assert seeds == {"res": TOE}
    assert model.dam_foot_cells == {"res": TOE}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.tolist() == [TOE]
    np.testing.assert_array_equal(record.receiver, descent.receiver)


def test_the_section_hands_the_feet_to_the_sidecar_write(monkeypatch, tmp_path) -> None:
    _declare_spillway(monkeypatch, declared=True)
    written = []

    def spy(descent, folder, stem, *, dam_foot_cells=None, basin=None):
        written.append(dict(dam_foot_cells))

    monkeypatch.setattr(build, "write_descent_sidecar", spy)

    _build(_model(tmp_path))

    assert written == [{"res": TOE}]


def test_a_lake_without_a_declared_spillway_has_no_foot_but_D_is_stored(
    monkeypatch, tmp_path
) -> None:
    _declare_spillway(monkeypatch, declared=False)
    model = _model(tmp_path)

    _, _, seeds = _build(model)

    assert seeds == {}
    assert model.dam_foot_cells == {}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.size == 0


# The descent sidecar reads back exactly what the build wrote, or refuses.
#
# The extractors never see the model: D reaches the run store through this file.
# Its arrays come back with their dtypes (receiver int64, surface float64, masks
# bool), its adjacency and epsilon, and the build report. An absent file reads as
# None; a file that lost an array or mixes cell counts is refused.


def _descent_2():
    nrow = ncol = 6
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    top = (10.0 + rows + np.abs(cols - 3)).astype(float)
    top[2 * ncol + 3] = 0.0  # a pit D raises
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top.reshape(nrow, ncol),
        botm=np.full((1, nrow, ncol), -10.0),
    )
    return build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)


def test_the_sidecar_round_trips(tmp_path) -> None:
    descent = _descent_2()

    path = write_descent_sidecar(descent, tmp_path, "model")
    record = read_descent_sidecar(path)

    assert path == tmp_path / "model.descent.npz"
    assert record is not None
    np.testing.assert_array_equal(record.receiver, descent.receiver)
    np.testing.assert_array_equal(record.surface, descent.surface)
    np.testing.assert_array_equal(record.base_level, descent.base_level)
    np.testing.assert_array_equal(record.channel, descent.channel)
    np.testing.assert_array_equal(record.pinned, descent.pinned)
    assert record.receiver.dtype == np.int64
    assert record.surface.dtype == np.float64
    assert record.base_level.dtype == bool
    assert record.adjacency == "shared_nodes"
    assert record.epsilon == DESCENT_EPSILON_M
    assert record.n_raised == descent.n_raised >= 1
    assert record.max_raise_m == descent.max_raise_m
    assert record.report()["n_raised"] == descent.n_raised


def test_an_absent_sidecar_reads_as_none(tmp_path) -> None:
    assert read_descent_sidecar(tmp_path / "model.descent.npz") is None


def test_a_sidecar_that_lost_an_array_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent_2(), tmp_path, "model")
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "surface"}
    np.savez(path, **kept)

    with pytest.raises(ValueError, match="lacks surface"):
        read_descent_sidecar(path)


def test_a_sidecar_that_mixes_cell_counts_is_refused(tmp_path) -> None:
    path = write_descent_sidecar(_descent_2(), tmp_path, "model")
    with np.load(path) as payload:
        arrays = {name: payload[name] for name in payload.files}
    arrays["channel"] = arrays["channel"][:-1]
    np.savez(path, **arrays)

    with pytest.raises(ValueError, match="mixes cell counts"):
        read_descent_sidecar(path)


# MODFLOW-NWT builds the descent D too, seeded on every constant-head cell it writes.
#
# NWT has no CHD support mask: its static constant heads are ``ibound == -1``,
# its transient ones are rows of the CHD package with ``ibound`` left at 1, and
# its inactive cells are ``ibound == 0``. D seeds on both kinds of constant head,
# as MODFLOW 6 seeds its CHD supports, leaves its sidecar beside the model and
# keeps itself there without its adjacency. The steady initialization builds none.

NROW = NCOL = 5


def _mesh_3() -> SolverMesh:
    rows, cols = np.divmod(np.arange(NROW * NCOL), NCOL)
    return solver_mesh_from_structured_arrays(
        nrow=NROW,
        ncol=NCOL,
        top=(10.0 + rows + cols).reshape(NROW, NCOL).astype(float),
        botm=np.full((2, NROW, NCOL), -10.0) - np.arange(2)[:, None, None],
    )


def _inputs() -> SimpleNamespace:
    ibound = np.ones((2, NROW, NCOL), dtype=int)
    ibound[1, 2, 2] = -1  # a static constant head in the lower layer only
    ibound[:, 0, 4] = 0  # an inactive column
    # A transient constant head: CHD rows in two periods, ibound left at 1.
    chd_spd = {0: [[0, 3, 1, 5.0, 5.0]], 1: [[0, 3, 1, 6.0, 6.0]]}
    return SimpleNamespace(ibound=ibound, chd_spd=chd_spd)


def test_the_nwt_build_seeds_d_on_every_constant_head_and_leaves_it_beside_the_model(
    tmp_path,
) -> None:
    model = SimpleNamespace(
        geographic=None, full_path=str(tmp_path), model_name="nwt", descent=None, auxiliary=False
    )

    descent = ModflowNwt._build_descent(model, _mesh_3(), _inputs())

    assert model.descent is descent
    assert descent.adjacency is None
    static, transient, inactive = 2 * NCOL + 2, 3 * NCOL + 1, 0 * NCOL + 4
    assert np.flatnonzero(descent.constant_head).tolist() == [static, transient]
    assert descent.base_level[static] and descent.base_level[transient]
    assert not descent.routable[inactive]
    assert not descent.pinned.any()
    record = read_descent_sidecar(tmp_path / "nwt.descent.npz")
    assert record is not None
    np.testing.assert_array_equal(record.receiver, descent.receiver)
    np.testing.assert_array_equal(record.constant_head, descent.constant_head)


def test_the_steady_initialization_builds_no_descent(tmp_path) -> None:
    model = SimpleNamespace(
        geographic=None, full_path=str(tmp_path), model_name="nwt", descent=None, auxiliary=True
    )

    assert ModflowNwt._build_descent(model, _mesh_3(), _inputs()) is None
    assert model.descent is None
    assert not list(tmp_path.glob("*.descent.npz"))


# The dam foot the production resolver gives draws the reach the saddle leaves out.
#
# On the dammed valley of ``_heads_dam`` the criterion leaves the reservoir through
# a saddle lower than the dam, so the reach below the dam has no head. The lake
# declares a spillway routed to the downstream reach: ``resolve_spillway_seed_cells``
# finds the crest cell below its shore nearest the outlet, ``resolve_dam_foot_cells``
# keeps it, and forcing it draws the reach. A lake without a declared spillway has
# no foot, so it forces nothing (its exit is the saddle D already takes).

LAKE_CELLS = [cell(row, col) for row in range(8, 12) for col in range(5, 8)]


def _dam_foot(monkeypatch, *, declared: bool) -> dict[str, int]:
    outlets = [{"mover": {"to_downstream_reach": True}}] if declared else []
    monkeypatch.setattr(
        lake_builder, "_active_lake_definitions", lambda model: {"res": {"outlets": outlets}}
    )
    n_cells = N_ROWS * N_COLS
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    planar = HydroMesh(
        vertices=vertices[:, :2], cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),)
    )
    centroids = np.asarray([centre(*divmod(c, N_COLS)) for c in range(n_cells)])
    seeds = resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": LAKE_CELLS},
        cell_adjacency=derive_geometry(planar).adjacency_sets(),
        cell_centroids=centroids,
        idomain=np.ones((1, n_cells), dtype=int),
        mesh_top=topography(),
        outlet_xy=centre(N_ROWS - 1, AXIS),
    )
    lake_of = np.full(n_cells, -1, dtype=int)
    lake_of[LAKE_CELLS] = 0
    descent = grid_descent(topography().reshape(N_ROWS, N_COLS), lake_of=lake_of)
    return resolve_dam_foot_cells(descent, seeds)


def test_a_declared_spillway_gives_the_crest_below_the_lake_as_the_foot(monkeypatch) -> None:
    feet = _dam_foot(monkeypatch, declared=True)

    assert feet == {"res": cell(12, AXIS)}


def test_the_reach_below_the_dam_is_drawn_with_that_foot_and_missing_without(monkeypatch) -> None:
    feet = _dam_foot(monkeypatch, declared=True)
    below_dam = cell(DAM_FOOT_ROW, AXIS)

    plain = dam_geometry()
    forced = dam_geometry(list(feet.values()))

    assert not plain.observed[below_dam]
    assert forced.observed[below_dam]
    downstream = forced.metric.graph.downstream
    walk = below_dam
    while walk >= 0:
        assert forced.observed[walk]
        walk = int(downstream[walk])
    assert forced.observed[forced.outlet]
    assert forced.diagnostics["n_forced_heads"] == 1.0
    assert not (plain.observed & ~forced.observed).any()


def test_a_lake_without_a_declared_spillway_has_no_foot_to_force(monkeypatch) -> None:
    assert _dam_foot(monkeypatch, declared=False) == {}


# With a cutoff wall, the foot of the spillway lies downstream of the wall.
#
# The foot was the lowest non-lake neighbor of the shore cell nearest the
# discharge point, with no look at the wall: it could fall on a bank beside the
# wall or behind it, and the release then entered the aquifer on the lake side.
# The wall has the lake on its left, so the foot is taken among the cells on its
# right (``downstream_of_wall``), as the HFB and the LAK seal read it.

# The wall runs north along x = 15: the lake (x < 15) is on its left.
_WALL = LineString([(15.0, -50.0), (15.0, 50.0)])


def _definitions(wall: LineString | None):
    definition = {"outlets": [{"mover": {"to_downstream_reach": True}}]}
    if wall is not None:
        definition["cutoff_wall_line"] = wall
    return lambda model: {"res": definition}


def _seed(monkeypatch, wall, *, centroids, adjacency, top, lake=(0, 1)) -> dict[str, int]:
    monkeypatch.setattr(lake_builder, "_active_lake_definitions", _definitions(wall))
    return resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": list(lake)},
        cell_adjacency=adjacency,
        cell_centroids=np.asarray(centroids, dtype=float),
        idomain=np.ones((1, len(top)), dtype=int),
        mesh_top=np.asarray(top, dtype=float),
        outlet_xy=(30.0, 0.0),
    )


# Lake {0, 1}. Shore cell 1 touches cell 2 (a bank on the lake side, x = 10, the
# lowest) and cell 3 (downstream of the wall, x = 20).
_CENTROIDS = [[0, 0], [10, 0], [10, 10], [20, 0]]


_ADJACENCY = [{1}, {0, 2, 3}, {1}, {1}]


_TOP = [100.0, 95.0, 70.0, 80.0]


def test_the_foot_without_a_wall_is_the_lowest_neighbour(monkeypatch) -> None:
    seeds = _seed(monkeypatch, None, centroids=_CENTROIDS, adjacency=_ADJACENCY, top=_TOP)
    assert seeds == {"res": 2}


def test_the_foot_with_a_wall_is_downstream_of_it(monkeypatch) -> None:
    seeds = _seed(monkeypatch, _WALL, centroids=_CENTROIDS, adjacency=_ADJACENCY, top=_TOP)
    assert seeds == {"res": 3}


def test_the_dam_is_the_shore_cell_that_faces_the_wall(monkeypatch) -> None:
    # The shore cell nearest the outlet (cell 1, at x = 12) only touches a bank on
    # the lake side (cell 2). Cell 0 is the one that faces the wall: its toe is 3.
    centroids = [[8, -20], [12, 0], [12, 10], [20, -20]]
    adjacency = [{1, 3}, {0, 2}, {1}, {0}]
    top = [100.0, 95.0, 70.0, 80.0]
    seeds = _seed(monkeypatch, _WALL, centroids=centroids, adjacency=adjacency, top=top)
    assert seeds == {"res": 3}


def test_a_wall_with_no_cell_downstream_on_the_shore_is_refused(monkeypatch) -> None:
    # The only non-lake neighbor is on the lake side: there is no foot below the wall.
    centroids = [[0, 0], [10, 0], [10, 10]]
    adjacency = [{1}, {0, 2}, {1}]
    with pytest.raises(ValueError, match="downstream of the cutoff wall"):
        _seed(monkeypatch, _WALL, centroids=centroids, adjacency=adjacency, top=[100, 95, 70])


# The build hands each lake's spillway to a reach that does not feed that lake.
#
# The reaches are numbered against the lake order of the build, and a reach's
# ``terminal_lake`` is the 1-based position of its lake there. The wiring in
# ``build.py`` read that label 0-based: with one lake the forbidden set was empty,
# with two lakes it forbade the feeders of the other lake. A spillway could then
# be routed to a feeder of its own lake and close a LAK -> SFR -> LAK loop.

_CENTROIDS_6 = np.array([[float(i) * 10.0, 0.0] for i in range(8)])


def _reach(ifno: int, cell: int, *, upstream=(), terminal_lake: int | None = None) -> NS:
    return NS(
        ifno=ifno,
        cellid=(0, cell),
        upstream=tuple(upstream),
        is_terminal_to_lake=terminal_lake is not None,
        terminal_lake=terminal_lake,
    )


def test_one_lake_refuses_a_spillway_on_a_feeder_of_its_own() -> None:
    # Reach 0 on cell 2 ends in the only lake (terminal_lake = 1). The toe seed is on it.
    network = NS(reaches=[_reach(0, 2, terminal_lake=1), _reach(1, 5)])
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        _resolve_spillway_receivers(
            {"cheze": network}, {"res": 2}, lake_ids=["res"], cell_centroids=_CENTROIDS_6
        )


def test_two_lakes_forbid_the_feeders_of_the_right_lake() -> None:
    # Lake order: res (1), forebay (2). Reach 1 on cell 3 ends in the forebay;
    # reach 0 on cell 2 feeds it from upstream. Reach 2 on cell 5 ends in res.
    network = NS(
        reaches=[
            _reach(0, 2),
            _reach(1, 3, upstream=(0,), terminal_lake=2),
            _reach(2, 5, terminal_lake=1),
        ]
    )
    # The forebay toe on a reach upstream of its own terminal: refused.
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        _resolve_spillway_receivers(
            {"cheze": network},
            {"forebay": 2},
            lake_ids=["res", "forebay"],
            cell_centroids=_CENTROIDS_6,
        )
    # The forebay spilling into a feeder of res is a cascade: allowed.
    assert _resolve_spillway_receivers(
        {"cheze": network},
        {"forebay": 5},
        lake_ids=["res", "forebay"],
        cell_centroids=_CENTROIDS_6,
    ) == {"forebay": 2}


# The solver adapter of D: inactive lakes are crossed, CHD cells seed, the top stays.
#
# A fixed-area lake is inactive in every layer of the solver, yet water crosses
# it: its cells must be on the descended graph. Lakes are numbered in the order
# build.py numbers LAK lakes in, the iteration order of the mapping.

N_7 = 7


def _cell(row: int, col: int) -> int:
    return row * N_7 + col


def _grid_mesh(inactive_mask: np.ndarray) -> SolverMesh:
    vertices, connectivity = quad_mesh(N_7, N_7)
    rows, cols = np.divmod(np.arange(N_7 * N_7), N_7)
    return solver_mesh_from(
        HydroMesh(
            vertices=vertices[:, :2],
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        ),
        top=20.0 + rows + cols,
        botm=np.stack([np.zeros(N_7 * N_7), np.full(N_7 * N_7, -10.0)]),
        inactive_mask=inactive_mask,
    )


def test_an_inactive_lake_is_on_the_graph_and_numbered_in_order() -> None:
    inactive = np.zeros((2, N_7 * N_7), dtype=bool)
    west_lake = [_cell(3, 1), _cell(3, 2)]
    east_lake = [_cell(3, 4), _cell(3, 5)]
    inactive[:, west_lake + east_lake] = True
    off_domain = _cell(5, 5)
    inactive[:, off_domain] = True
    deeper_only = _cell(1, 3)
    inactive[0, deeper_only] = True
    mesh = _grid_mesh(inactive)
    top_before = mesh.top.copy()

    descent = build_solver_mesh_descent(
        mesh,
        lake_cells_by_lake={"east": east_lake, "west": west_lake},
        base_level_mask=None,
    )

    assert np.all(descent.routable[west_lake + east_lake])
    assert descent.routable[deeper_only]
    assert not descent.routable[off_domain]
    assert descent.lake_of[east_lake].tolist() == [0, 0]
    assert descent.lake_of[west_lake].tolist() == [1, 1]
    assert np.array_equal(mesh.top, top_before)


def test_a_constant_head_cell_seeds_the_descent(caplog) -> None:
    mesh = _grid_mesh(np.zeros((2, N_7 * N_7), dtype=bool))
    pit = _cell(3, 3)
    top = mesh.top.copy()
    top[pit] = 0.0
    mesh = solver_mesh_from(
        mesh.planar_mesh, top=top, botm=mesh.botm, inactive_mask=mesh.inactive_mask
    )
    base_level = np.zeros(N_7 * N_7, dtype=bool)
    base_level[pit] = True

    with caplog.at_level(logging.INFO):
        descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)

    assert descent.base_level[pit]
    assert descent.n_raised == 0
    assert "shared nodes (D8)" in caplog.text


def test_a_ragged_polygon_mesh_descends_by_shared_faces() -> None:
    # One quad and two triangles: the first triangle meets the quad at a node only.
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]])
    cells = ([0, 1, 4, 3], [1, 2, 5], [1, 5, 4])
    mesh = solver_mesh_from(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),)),
        top=np.array([3.0, 1.0, 2.0]),
        botm=np.zeros((1, 3)),
        inactive_mask=np.zeros((1, 3), dtype=bool),
    )

    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)

    assert not descent.diagonal_neighbors
    assert [sorted(cells) for cells in descent.adjacency] == [[2], [2], [0, 1]]


# The MODFLOW 6 budget zone ``catchment`` is the basin of D the build kept.
#
# The budget is computed before the Zarr store is written, so the extractor reads
# the basin from the descent sidecar, never from a second computation. A build
# that left none (no sidecar, a sidecar written before the basin was stored, an
# unreadable one) keeps the old support ``polygon_centroid`` and says so.

TOP = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])


N_CELLS = TOP.size


class _NoStore:
    """A store that holds no watershed, so the old support finds nothing to place."""

    def read_geographic_feature(self, sim_id, name):
        del sim_id, name
        return None


def _basin_8(rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[1, 2, 4, 5]] = True
    return DescentBasin(mask=mask, outlet=4, rule=rule, area_m2=4.0e6, seeded_at_outlet=False)


def _zone(folder, store=None) -> np.ndarray | None:
    return Modflow6OutputAdapter()._catchment_cell_mask(
        "sim", store if store is not None else _NoStore(), folder, n_cells=N_CELLS
    )


def test_the_zone_is_the_basin_in_the_sidecar(tmp_path, caplog) -> None:
    basin = _basin_8()
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=basin)

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    np.testing.assert_array_equal(zone, basin.mask)
    assert "the basin of D, 4 of 9 cells (4.000 km2)" in caplog.text
    assert "polygon_centroid" not in caplog.text


def test_the_zone_does_not_compute_the_basin_again(tmp_path, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("the budget zone computed the basin of D again")

    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin_8())
    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)

    np.testing.assert_array_equal(_zone(tmp_path), _basin_8().mask)


def test_the_largest_basin_of_a_synthetic_domain_is_no_zone(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin_8("largest_basin"))

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    assert zone is None
    assert "polygon_centroid" not in caplog.text


@pytest.mark.parametrize(
    ("make_sidecar", "reason"),
    [
        pytest.param(lambda folder: None, "no descent sidecar", id="no_sidecar"),
        pytest.param(
            lambda folder: write_descent_sidecar(grid_descent(TOP), folder, "model"),
            "a sidecar written before the basin was stored",
            id="before_the_basin",
        ),
    ],
)
def test_a_build_without_a_basin_keeps_the_old_support_and_says_so(
    tmp_path, caplog, make_sidecar, reason
) -> None:
    make_sidecar(tmp_path)

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    assert zone is None
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        f"Budget zone 'catchment' for sim sim: the build left no basin of D ({reason}), so the "
        "zone keeps the old support 'polygon_centroid'."
    ]


def test_a_basin_of_another_size_than_the_mesh_is_not_used(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin_8())

    with caplog.at_level(logging.INFO):
        zone = Modflow6OutputAdapter()._catchment_cell_mask(
            "sim", _NoStore(), tmp_path, n_cells=N_CELLS + 1
        )

    assert zone is None
    assert "a basin of 9 cells on a mesh of 10" in caplog.text
