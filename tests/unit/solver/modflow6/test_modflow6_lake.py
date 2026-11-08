from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import LineString, Polygon, box

from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.sinks_sources.lake import BathymetryReconstructionConfig
from hydromodpy.results.exporters.export_spec import ExportKind
from hydromodpy.results.exporters.vocabulary import SIMULATED_SERIES, export_kind
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    cutoff_wall_faces,
    downstream_of_wall,
    interior_cells,
    lake_shore_faces,
    polygon_overlap,
    wall_leaks,
)
from hydromodpy.solver.modflow6.builders.lake import (
    build_exposed_band_runoff_specs,
    build_lak_package_args,
    build_lake_table,
)
from hydromodpy.solver.modflow6.builders.lake_cells import (
    apply_lake_idomain_mask,
    resolve_lake_cells,
)
from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow6.builders.recharge import (
    build_evt_stress_period_data,
    mask_recharge_on_lake_cells,
)
from hydromodpy.solver.modflow6.builders.sfr import (
    build_drainage_mover_records,
    mover_rows_reach_lake,
)
from hydromodpy.solver.modflow6.extractors import lake as lake_extractor
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.support.lake_band_runoff import (
    LakeBandRunoffSpec,
    exposed_band_area,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import resolve_modflow_runner
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh, square_domain, voronoi_lake_mesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from validation_cases.numerical.steady.lak_merritt_konikow_p01.geometry import load_geometry
from validation_cases.numerical.steady.lak_merritt_konikow_p01.runtime_lak import (
    build_hmp_connectiondata,
    build_hmp_solver_mesh,
)
from validation_cases.shared import load_case_tolerances

# On a mesh whose faces do not follow the shore, a lake owns the cells flopy's GridIntersect gave.
#
# The LAK builder resolved a lake polygon with ``flopy.utils.GridIntersect`` on a
# ``VertexGrid`` rebuilt from the mesh, then recomputed each overlap area with
# shapely. It now reads the cell mesh: the cells the polygon overlaps by a
# positive area, with that area. The two are compared on a regular grid at a
# non-integer origin, on the triangles and on the Voronoi dual of a committed
# bundle: same cells, areas within 1e-9.

_AREA_RTOL = 1e-9


_BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"


_UNIT_LAKES = (
    Polygon([(0.2, 0.25), (0.55, 0.18), (0.71, 0.47), (0.48, 0.69), (0.23, 0.58)]),
    Polygon(
        [(0.6, 0.6), (0.92, 0.62), (0.88, 0.9), (0.62, 0.86)],
        holes=[[(0.7, 0.7), (0.8, 0.71), (0.78, 0.8), (0.71, 0.79)]],
    ),
)


def _regular() -> PlanarCellMesh:
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


def _meshes() -> dict[str, PlanarCellMesh]:
    return {
        "regular": _regular(),
        "triangles": bundle_triangles(_BUNDLE),
        "dual": bundle_dual(_BUNDLE),
    }


def _lakes_on(cell_mesh: PlanarCellMesh) -> list[Polygon]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(lake, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for lake in _UNIT_LAKES
    ]


def _gridintersect_lake(cell_mesh: PlanarCellMesh, polygon: Polygon) -> dict[int, float]:
    """The rule of the former builder: GridIntersect cells, overlap recomputed by shapely."""
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
    result = GridIntersect(grid).intersect(polygon, geo_dataframe=False)
    verts = np.asarray(grid.verts)
    areas = {}
    for cell in sorted({int(c) for c in np.asarray(result["cellids"]).ravel()}):
        ring = verts[[int(i) for i in grid.cell2d[cell][4:] if int(i) >= 0]][:, :2]
        areas[cell] = float(Polygon(ring).intersection(polygon).area)
    return areas


@pytest.mark.parametrize("name", ["regular", "triangles", "dual"])
def test_the_lake_cells_and_areas_are_those_of_gridintersect(name: str) -> None:
    cell_mesh = _meshes()[name]
    for index, lake in enumerate(_lakes_on(cell_mesh)):
        expected = _gridintersect_lake(cell_mesh, lake)
        cells, areas = resolve_lake_cells(
            None, lake_id=f"lake{index}", polygon=lake, cell_mesh=cell_mesh, with_areas=True
        )
        assert cells == sorted(expected)
        got = np.array([areas[c] for c in cells])
        want = np.array([expected[c] for c in cells])
        np.testing.assert_allclose(got, want, rtol=_AREA_RTOL, atol=_AREA_RTOL * lake.area)
        assert sum(areas.values()) == pytest.approx(lake.area, rel=_AREA_RTOL)


# A shore the generated mesh follows only in part is resolved by overlap, not refused.
#
# The voronoi engine yields a shore segment where a lake arm is narrower than a
# cell, so the ``lakes`` faces no longer enclose the lake. The regions they bound
# then stand for nothing, and the lake owns the cells its polygon overlaps.

X0, Y0 = L93_ORIGIN


CELL_M = 40.0


_AREA_RTOL_1 = 1e-6


def _lake(*points: tuple[float, float]) -> Polygon:
    return Polygon([(X0 + x, Y0 + y) for x, y in points])


SQUARE = _lake((300, 300), (700, 300), (700, 700), (300, 700))


WITH_ARM = _lake(
    (300, 300), (700, 300), (700, 500), (950, 500), (950, 512), (700, 512), (700, 700), (300, 700)
)


def _mesh(lake: Polygon) -> PlanarCellMesh:
    domain = square_domain(1000.0, x0=X0, y0=Y0)
    return voronoi_lake_mesh(lake, domain=domain, pixel=20.0, cell_size=CELL_M)


def test_a_shore_followed_whole_gives_whole_cells() -> None:
    mesh = _mesh(SQUARE)
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=SQUARE, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] == pytest.approx(1.0)
    np.testing.assert_array_equal([areas[c] for c in cells], mesh.geometry.areas[cells])
    assert sum(areas.values()) == pytest.approx(SQUARE.area, rel=_AREA_RTOL_1)


def test_a_shore_followed_in_part_is_resolved_by_overlap() -> None:
    mesh = _mesh(WITH_ARM)
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=WITH_ARM, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] < 0.99
    assert cells
    assert sum(areas.values()) == pytest.approx(WITH_ARM.area, rel=_AREA_RTOL_1)


# Lake cells must be made inactive before DISV is built.
#
# LAK lays the lake on the existing grid by deactivating the occupied cells
# (``idomain = 0``) and supplying the storage / exchange itself. The mask must be
# applied on a *copy* of the frozen ``SolverMesh`` so the original survives, and it
# must zero the active domain on exactly the lake cells' occupied layers (leaving
# an active aquifer cell below for the LAK VERTICAL connection) so RCH, EVT and
# DRN stay consistent with the footprint.


def _grid(nrow: int, ncol: int, nlay: int = 3) -> SolverMesh:
    top = np.full((nrow, ncol), 10.0)
    botm = np.stack([np.full((nrow, ncol), 10.0 - (lay + 1) * 3.0) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)


def test_apply_lake_idomain_mask_deactivates_surface_layer_of_lake_cells() -> None:
    mesh = _grid(3, 3, nlay=3)
    # Central cell (row 1, col 1) -> flat id 4 in row-major order.
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [4]})

    idomain = masked.idomain
    assert idomain.shape == (3, 9)
    # Lake cell inactive on the occupied (top) layer ...
    assert idomain[0, 4] == 0
    # ... but the aquifer below stays active for the VERTICAL connection.
    assert idomain[1, 4] == 1
    assert idomain[2, 4] == 1
    # Every other cell stays active on every layer.
    active_cells = [c for c in range(9) if c != 4]
    assert np.all(idomain[:, active_cells] == 1)


def test_apply_lake_idomain_mask_respects_occupied_layers() -> None:
    mesh = _grid(2, 2, nlay=3)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0]}, occupied_layers=2)
    idomain = masked.idomain
    assert idomain[0, 0] == 0
    assert idomain[1, 0] == 0
    # The deepest layer stays active so the lake has somewhere to leak.
    assert idomain[2, 0] == 1


def test_apply_lake_idomain_mask_leaves_original_mesh_unchanged() -> None:
    mesh = _grid(2, 3, nlay=2)
    before = mesh.idomain.copy()

    apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0, 1]})

    # The frozen mesh is replaced, never mutated in place.
    assert np.array_equal(mesh.idomain, before)
    assert np.all(mesh.idomain == 1)


def test_apply_lake_idomain_mask_rejects_full_column_occupation() -> None:
    mesh = _grid(2, 2, nlay=2)
    with pytest.raises(ValueError, match="at least one active layer"):
        apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0]}, occupied_layers=2)


def test_apply_lake_idomain_mask_handles_multiple_lakes() -> None:
    mesh = _grid(2, 4, nlay=2)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0], "lac1": [7]})
    idomain = masked.idomain
    assert idomain[0, 0] == 0
    assert idomain[0, 7] == 0
    assert idomain[0, [1, 2, 3, 4, 5, 6]].tolist() == [1, 1, 1, 1, 1, 1]


def test_apply_lake_idomain_mask_respects_per_lake_occupied_layers() -> None:
    # A surface lake (1 layer) and a deep reservoir (2 layers) on the same grid
    # are deactivated to different depths via occupied_layers_by_lake.
    mesh = _grid(2, 2, nlay=3)
    masked = apply_lake_idomain_mask(
        mesh,
        lake_cell_ids_by_lake={"surface": [0], "deep": [3]},
        occupied_layers_by_lake={"surface": 1, "deep": 2},
    )
    idomain = masked.idomain
    # Surface lake: only layer 0 inactive.
    assert idomain[0, 0] == 0
    assert idomain[1, 0] == 1
    # Deep reservoir: layers 0 and 1 inactive, layer 2 stays active.
    assert idomain[0, 3] == 0
    assert idomain[1, 3] == 0
    assert idomain[2, 3] == 1


def test_apply_lake_idomain_mask_per_lake_rejects_full_column() -> None:
    mesh = _grid(2, 2, nlay=2)
    with pytest.raises(ValueError, match="at least one active layer"):
        apply_lake_idomain_mask(
            mesh,
            lake_cell_ids_by_lake={"deep": [0]},
            occupied_layers_by_lake={"deep": 2},
        )


# Aquifer RCH/EVT must be zeroed on lake cells to avoid double counting.
#
# The lake's own rainfall and open-water evaporation enter through LAK, so applying
# RCHA or aquifer EVT on the same cells would count those fluxes twice. The recharge
# masking zeros exactly the lake cells; the EVT builder skips them entirely.


def test_mask_recharge_zeros_only_lake_cells() -> None:
    spd = {0: np.full(6, 1.0e-8), 1: np.full(6, 2.0e-8)}
    masked = mask_recharge_on_lake_cells(spd, lake_cell_ids=[1, 4])

    for kper, expected_nonzero in ((0, 1.0e-8), (1, 2.0e-8)):
        arr = masked[kper]
        assert arr[1] == 0.0
        assert arr[4] == 0.0
        # Non-lake cells keep their recharge.
        assert arr[0] == expected_nonzero
        assert arr[[2, 3, 5]].tolist() == [expected_nonzero] * 3


def test_mask_recharge_no_lake_is_a_noop() -> None:
    spd = {0: np.full(4, 3.0e-8)}
    masked = mask_recharge_on_lake_cells(spd, lake_cell_ids=[])
    assert np.all(masked[0] == 3.0e-8)


def _evt_model() -> tuple[SimpleNamespace, SolverMesh]:
    nrow, ncol = 2, 3
    top = np.full((nrow, ncol), 10.0)
    botm = np.stack([np.full((nrow, ncol), 5.0), np.full((nrow, ncol), 0.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)
    return SimpleNamespace(
        ncpl=nrow * ncol,
        nper=1,
        modflow_config=_coerce_modflow6_config(None),
        _evt_rate_payload={0: 1.0e-8},  # uniform routed deficit (m/s)
    ), mesh


def test_evt_skips_lake_cells() -> None:
    model, mesh = _evt_model()
    # lake_cell_ids is passed explicitly (not read off the model) so the masking
    # does not depend on build ordering.
    evt_spd = build_evt_stress_period_data(
        model,
        mesh,
        ocean_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        stream_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        lake_cell_ids=[2, 4],
    )
    assert evt_spd is not None
    cells_with_evt = {int(entry[1]) for entry in evt_spd[0]}
    # Lake cells carry no aquifer EVT record.
    assert 2 not in cells_with_evt
    assert 4 not in cells_with_evt
    # Every other cell does get one.
    assert cells_with_evt == {0, 1, 3, 5}


def test_evt_without_lake_cells_covers_every_cell() -> None:
    model, mesh = _evt_model()
    evt_spd = build_evt_stress_period_data(
        model,
        mesh,
        ocean_support_mask=np.zeros(mesh.n_cells, dtype=bool),
        stream_support_mask=np.zeros(mesh.n_cells, dtype=bool),
    )
    assert evt_spd is not None
    assert {int(entry[1]) for entry in evt_spd[0]} == set(range(mesh.n_cells))


# The LAK stage-volume-area abacus feeding ``ModflowUtllaktab``.
#
# MF6 interpolates the abacus and extrapolates poorly outside it, so the builder
# sorts by stage and rejects any table MF6 would abort on: stage and volume must
# strictly increase and surface area must be non-decreasing and non-negative.


def test_build_lake_table_sorts_by_stage_and_returns_triples() -> None:
    abacus = [
        (12.0, 50.0, 20.0),
        (10.0, 0.0, 5.0),
        (11.0, 20.0, 12.0),
    ]
    table = build_lake_table(None, lake_id="lac0", abacus=abacus)

    stages = [row[0] for row in table]
    assert stages == [10.0, 11.0, 12.0]  # sorted ascending
    assert all(len(row) == 3 for row in table)
    # Strictly increasing stage axis.
    assert all(b > a for a, b in pairwise(stages))


def test_build_lake_table_accepts_column_mapping() -> None:
    abacus = {"stage": [10.0, 11.0], "volume": [0.0, 20.0], "sarea": [5.0, 12.0]}
    table = build_lake_table(None, lake_id="lac0", abacus=abacus)
    assert table == [(10.0, 0.0, 5.0), (11.0, 20.0, 12.0)]


def test_build_lake_table_rejects_decreasing_volume() -> None:
    abacus = [(10.0, 30.0, 5.0), (11.0, 20.0, 12.0)]
    with pytest.raises(ValueError, match="volume must strictly increase"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_equal_volume() -> None:
    # MF6 lak_read_table requires strictly increasing volume (v <= v0 aborts).
    abacus = [(10.0, 20.0, 5.0), (11.0, 20.0, 12.0)]
    with pytest.raises(ValueError, match="volume must strictly increase"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_decreasing_sarea() -> None:
    abacus = [(10.0, 10.0, 12.0), (11.0, 20.0, 5.0)]
    with pytest.raises(ValueError, match="surface area must not decrease"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_duplicate_stage() -> None:
    abacus = [(10.0, 0.0, 5.0), (10.0, 20.0, 12.0)]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_negative_area() -> None:
    abacus = [(10.0, 0.0, 5.0), (11.0, 20.0, -1.0)]
    with pytest.raises(ValueError, match="must be"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_requires_two_rows() -> None:
    with pytest.raises(ValueError, match="at least two rows"):
        build_lake_table(None, lake_id="lac0", abacus=[(10.0, 0.0, 5.0)])


# The cells a lake owns and the faces of a cutoff wall laid on its shore.
#
# A lake owns its closed regions, and the cells outside them it covers for most of
# their area. The faces of a generated Voronoi mesh follow the lake shore smoothed
# at the cell size, so an arm narrower than a cell lies outside the lake regions.
# The cells of that arm the lake covers for more than half still belong to it, as
# a whole; a cell it only grazes does not.
#
# A cutoff wall runs with the lake on its left. Its shore faces join a lake cell
# to a cell across the wall, and a wall that misses one of its faces leaks.

X0, Y0 = L93_ORIGIN


BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)


ARM = box(X0 + 700.0, Y0 + 430.0, X0 + 950.0, Y0 + 470.0)


def _mesh_on_the_body_ring():
    """The Voronoi mesh of a 1.2 x 0.9 km domain whose faces follow the body of the lake."""
    return voronoi_lake_mesh(
        shapely.normalize(BODY),
        domain=box(X0, Y0, X0 + 1200.0, Y0 + 900.0),
        pixel=10.0,
        cell_size=30.0,
    )


def test_the_arm_cells_the_lake_covers_for_most_of_their_area_join_it() -> None:
    mesh = _mesh_on_the_body_ring()
    lake = BODY.union(ARM)
    cells = interior_cells(mesh, "lakes", lake)
    overlap_cells, overlap = polygon_overlap(mesh, lake)
    share = np.zeros(mesh.n_cells)
    share[overlap_cells] = overlap / mesh.geometry.areas[overlap_cells]
    in_arm = shapely.contains(ARM.buffer(1.0), shapely.points(mesh.centers))

    assert mesh.qa.families["lakes"]["covered_length_rel"] > 1.0 - 1e-6
    assert np.any(in_arm & (share > 0.5))
    assert set(np.flatnonzero(in_arm & (share > 0.5)).tolist()) <= set(cells.tolist())
    outside_body = cells[~shapely.contains(BODY, shapely.points(mesh.centers[cells]))]
    assert np.all(share[outside_body] > 0.5)


def test_a_lake_off_every_region_still_owns_nothing() -> None:
    mesh = _mesh_on_the_body_ring()

    assert interior_cells(mesh, "lakes", ARM).size == 0


def test_a_box_overlaps_the_grid_cells_by_the_area_it_covers() -> None:
    grid = regular_mesh(3, 4, dx=10.0)

    cells, overlap = polygon_overlap(grid, box(0.0, 0.0, 15.0, 30.0))
    assert cells.tolist() == [0, 1, 4, 5, 8, 9]
    np.testing.assert_allclose(overlap, [100.0, 50.0] * 3)


def _quad_grid(ncol: int, nrow: int) -> PlanarCellMesh:
    """``ncol`` by ``nrow`` unit cells on [0, ncol] x [0, nrow]; row 0 is north."""
    return regular_mesh(nrow, ncol)


# A 6 x 6 grid with the lake on the 2 x 6 strip of its two western columns. The wall
# runs north along x = 2, lake on its left, across the whole grid.
_LAKE = [j * 6 + i for j in range(6) for i in range(2)]


_WALL = LineString([(2.0, 0.0), (2.0, 6.0)])


def test_a_point_round_the_end_of_the_wall_is_not_downstream() -> None:
    points = np.array([[2.5, 3.0], [1.5, 3.0], [2.5, 7.0], [2.0, 3.0]])
    assert downstream_of_wall(_WALL, points).tolist() == [True, False, False, False]


def test_the_shore_faces_are_the_lake_faces_across_the_wall() -> None:
    cell_mesh = _quad_grid(6, 6)
    rows = lake_shore_faces(cell_mesh, _WALL, np.array(_LAKE))
    pairs = {tuple(pair) for pair in cell_mesh.geometry.edge_cells[rows].tolist()}
    assert pairs == {(j * 6 + 1, j * 6 + 2) for j in range(6)}


def test_a_wall_missing_a_face_leaks_and_a_whole_wall_does_not() -> None:
    cell_mesh = _quad_grid(6, 6)
    lake = np.array(_LAKE)
    faces = cutoff_wall_faces(cell_mesh, _WALL, lake)
    assert len(faces) == 6
    assert wall_leaks(cell_mesh, _WALL, lake, faces, reach=3.0).size == 0
    assert wall_leaks(cell_mesh, _WALL, lake, faces[1:], reach=3.0).size > 0


def test_a_wall_away_from_the_lake_and_the_mesh_bars_nothing() -> None:
    far = LineString([(20.0, 0.0), (20.0, 6.0)])

    assert cutoff_wall_faces(_quad_grid(6, 6), far, np.array(_LAKE)) == []


# The home-grown DISV LAK builder reproduces the ex-gwf-lak-p01 footprint.
#
# ``flopy.mf6.utils.get_lak_connections`` on the Merritt & Konikow (2000) test-1
# grid (single surface lake, 5x5 cells on layer 0) yields 45 connections: 25
# VERTICAL (one per lake cell, to the active cell below) and 20 HORIZONTAL (the
# perimeter edges). This test pins the home-grown DISV builder to that exact set
# WITHOUT running a solver, isolating the CONNECTIONDATA path that production uses
# in place of ``get_lak_connections`` (which does not support DISV lakes).
#
# The expected counts come from the case's documented structural tolerances, so a
# drift in either the builder or the published footprint fails here.


def _structural_tolerances() -> dict:
    from validation_cases.numerical.steady.lak_merritt_konikow_p01.geometry import CASE_DIR

    return dict(load_case_tolerances(CASE_DIR)["structural"])


def test_connectiondata_matches_published_vertical_horizontal_split() -> None:
    tol = _structural_tolerances()
    rows = build_hmp_connectiondata()

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]

    assert len(rows) == int(tol["n_connections"]) == 45
    assert len(vertical) == int(tol["n_vertical"]) == 25
    assert len(horizontal) == int(tol["n_horizontal"]) == 20
    # Negative invariant: a different split must NOT be produced (e.g. a missed
    # perimeter edge or a doubled vertical would change these counts).
    assert len(vertical) != len(horizontal)


def test_exactly_one_vertical_connection_per_lake_cell() -> None:
    geometry = load_geometry()
    rows = build_hmp_connectiondata(geometry)

    vertical = [r for r in rows if r[3] == "VERTICAL"]
    # One VERTICAL per lake cell, each pointing at layer 1 (first active below the
    # surface lake in layer 0).
    vert_cells = sorted(int(r[2][1]) for r in vertical)
    assert vert_cells == sorted(geometry.lake_cell_ids)
    assert all(r[2][0] == 1 for r in vertical)


def test_horizontal_connections_are_geometrically_valid() -> None:
    geometry = load_geometry()
    lake_set = set(geometry.lake_cell_ids)
    rows = build_hmp_connectiondata(geometry)

    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert horizontal
    for row in horizontal:
        lay, neighbour = int(row[2][0]), int(row[2][1])
        assert lay == 0  # surface lake occupies layer 0
        # Bank seepage never connects a lake cell to another lake cell.
        assert neighbour not in lake_set
        connlen = float(row[7])
        connwidth = float(row[8])
        assert connlen > 0.0
        assert connwidth > 0.0


def test_lake_cells_are_inactive_on_the_surface_layer() -> None:
    geometry = load_geometry()
    mesh = build_hmp_solver_mesh(geometry)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": geometry.lake_cell_ids})

    idomain = masked.idomain
    lake_cells = geometry.lake_cell_ids
    # idomain = 0 on exactly the lake cells in layer 0, and 1 everywhere else.
    assert np.all(idomain[0, lake_cells] == 0)
    assert np.all(idomain[1:, lake_cells] == 1)
    non_lake = [c for c in range(geometry.n_cells) if c not in set(lake_cells)]
    assert np.all(idomain[:, non_lake] == 1)


# Unit tests for the exposed-band (marnage) runoff sizing (no live solver).

_BED = np.array([10.0, 20.0, 30.0, 40.0, 50.0])


_AREA = np.full(5, 10000.0)


def test_exposed_band_area_grows_as_stage_drops():
    # Stage above every bed -> nothing exposed.
    assert exposed_band_area(_BED, _AREA, 60.0) == 0.0
    # Stage 35 -> beds 40 and 50 are exposed (>= stage) -> 2 cells.
    assert exposed_band_area(_BED, _AREA, 35.0) == 2 * 10000.0
    # Stage below every bed -> whole footprint exposed.
    assert exposed_band_area(_BED, _AREA, 5.0) == 5 * 10000.0


def test_runoff_at_adds_band_to_base():
    spec = LakeBandRunoffSpec(
        pkg="LAK",
        lake_index=0,
        bed=_BED,
        area=_AREA,
        rate_per_period=(2.0e-7, 2.0e-7),
        base_runoff_per_period=(1.0e-3, 1.0e-3),
    )
    # Period 0, full pool (stage 60): only the base runoff.
    assert spec.runoff_at(60.0, 0) == 1.0e-3
    # Period 1, drawn down (stage 35): base + rate * 20000.
    assert spec.runoff_at(35.0, 1) == 1.0e-3 + 2.0e-7 * 20000.0


def test_runoff_at_clamps_period_index_and_empty_rates():
    spec = LakeBandRunoffSpec(pkg=None, lake_index=0, bed=_BED, area=_AREA, rate_per_period=())
    # No rate and no base -> zero, and an out-of-range kper is clamped.
    assert spec.runoff_at(35.0, 99) == 0.0


# Auto-activation wiring of the exposed-band (marnage) runoff coupling.


def test_exposed_band_runoff_requires_dynamic_area():
    with pytest.raises(ValueError, match="dynamic_area"):
        BathymetryReconstructionConfig(exposed_band_runoff=True)
    # With dynamic_area it validates.
    cfg = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=True)
    assert cfg.exposed_band_runoff is True


class _Model:
    def __init__(self, lakes, reconstruction, marnage):
        self.inputs = make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes=lakes,
        )
        self._lake_bed_reconstruction = reconstruction
        self._marnage_lake_ids = marnage
        self._exposed_band_runoff_specs = None

    def required_runner(self) -> str:
        """The dispatch MODFLOW 6 declares, as the real model declares it."""
        return "api" if self._exposed_band_runoff_specs else "subprocess"


def _marnage_lake(*, exposed_band: bool):
    cfg = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=exposed_band)
    payload = {
        "bed_reconstruction": cfg,
        "runoff_rate": {"kind": "values", "values": [2.0e-7, 2.0e-7]},
        "runoff": None,  # SFR-routed: no direct lake runoff volume
    }
    reconstruction = {
        "lac0": {
            "bed_by_cell": {0: 10.0, 1: 20.0, 2: 30.0},
            "area_by_cell": {0: 1.0e4, 1: 1.0e4, 2: 1.0e4},
        }
    }
    return _Model({"lac0": payload}, reconstruction, {"lac0"})


def test_build_specs_for_marnage_lake():
    model = _marnage_lake(exposed_band=True)
    specs = build_exposed_band_runoff_specs(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.lake_index == 0
    assert spec.pkg == "LAK"
    assert tuple(spec.rate_per_period) == (2.0e-7, 2.0e-7)
    assert tuple(spec.base_runoff_per_period) == ()  # SFR-routed: band is the only runoff
    # Drawn down to stage 25: beds 30 only exposed -> 1 cell.
    assert spec.runoff_at(25.0, 0) == pytest.approx(2.0e-7 * 1.0e4)


def test_build_specs_empty_without_flag():
    model = _marnage_lake(exposed_band=False)
    assert build_exposed_band_runoff_specs(model) == []


def test_resolve_runner_forces_api_with_specs():
    model = _marnage_lake(exposed_band=True)
    model._exposed_band_runoff_specs = build_exposed_band_runoff_specs(model)
    assert resolve_modflow_runner(model) == "api"

    class _Bare:
        """A backend that declares no dispatch, as MODFLOW-NWT does."""

    assert resolve_modflow_runner(_Bare()) == "subprocess"


# A lake fed only by the hillslope drainage still announces MOVER.
#
# ``route_drainage`` hands each drain cell to the first reach or lake it meets on
# the descent. When the only mover entering a lake comes from DRN, LAK must
# advertise MOVER all the same, or MODFLOW 6 stops at the first DRN-to-LAK record.


def _one_lake_model() -> SimpleNamespace:
    polygon = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    return SimpleNamespace(
        model_output_name="drn_to_lake",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "lac0": {
                    "polygon": polygon,
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                    "initial_stage": 60.0,
                    "outlets": [],
                }
            },
        ),
    )


def _lake_args(*, external_mover_to_lake: bool) -> dict:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 50.0), np.full((4, 4), 0.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    cells = {"lac0": [0, 1]}
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(
        _one_lake_model(),
        solver_mesh=masked,
        lake_cell_ids_by_lake=cells,
        external_mover_to_lake=external_mover_to_lake,
    )
    assert args is not None
    return args


def _drain_chain_ending_in_a_lake() -> list[list[object]]:
    """MVR rows of a hillslope chain 0 -> 1 -> 2 whose cell 2 is lake number 0."""
    from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork

    receiver = np.array([1, 2, -1])
    faces: list[set[int]] = [{1}, {0, 2}, {1}]
    records = build_drainage_mover_records(
        {"net0": ResolvedSfrNetwork("net0", (), {"route_drainage": True})},
        drn_spd={0: [[0, 0, 100.0, 0.05], [0, 1, 100.0, 0.05]]},
        receiver=receiver,
        basin_cell_mask=np.ones(3, dtype=bool),
        face_adjacency=faces,
        mesh_top=np.zeros(3),
        lake_cells_by_number={0: [2]},
    )
    return build_mvr_period_records(records)


def test_a_drn_row_with_a_lake_receiver_is_counted() -> None:
    rows = _drain_chain_ending_in_a_lake()

    assert [row[2] for row in rows] == ["LAK", "LAK"]
    assert mover_rows_reach_lake(rows) is True


def test_a_drn_row_with_a_reach_receiver_is_not() -> None:
    assert mover_rows_reach_lake([["DRN", 0, "SFR", 3, "FACTOR", 1.0]]) is False
    assert mover_rows_reach_lake([]) is False


def test_lak_announces_mover_when_only_the_drainage_feeds_it() -> None:
    fed = mover_rows_reach_lake(_drain_chain_ending_in_a_lake())

    assert _lake_args(external_mover_to_lake=fed)["mover"] is True
    assert "mover" not in _lake_args(external_mover_to_lake=False)


# The package-agnostic MVR record builder.
#
# The general :func:`build_mvr_period_records` knows nothing about LAK: it formats
# and validates :class:`MoverRecord` transfers between any two named packages. The
# tests check that:
#
# * records keep their provider / receiver package names and ids untouched, for a
#   mix of packages (SFR, LAK, MAW);
# * :func:`mover_package_count` counts the distinct package names referenced;
# * an unknown ``mvrtype`` is rejected;
# * a negative ``value`` is rejected.


def test_records_are_package_agnostic() -> None:
    # A mix of providers / receivers across SFR, LAK and MAW formats unchanged.
    moves = [
        MoverRecord("SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0),
        MoverRecord("MAW-1", 1, "SFR-1", 5, "UPTO", 3.0),
    ]
    records = build_mvr_period_records(moves)
    assert records == [
        ["SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0],
        ["MAW-1", 1, "SFR-1", 5, "UPTO", 3.0],
    ]
    # SFR-1, LAK-1 and MAW-1 are three distinct packages.
    assert mover_package_count(records) == 3


def test_unknown_mvrtype_is_rejected() -> None:
    with pytest.raises(ValueError, match="mvrtype must be one of"):
        build_mvr_period_records([MoverRecord("SFR-1", 0, "LAK-1", 0, "SIPHON", 1.0)])


def test_negative_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="value must be >= 0"):
        build_mvr_period_records([MoverRecord("SFR-1", 0, "LAK-1", 0, "FACTOR", -1.0)])


# Every series the LAK extractor writes is a name ``[[export]]`` and ``hmp export`` know.
#
# ``outlet_inflow`` (what a lake receives from another lake's outlets) and the
# flow through the cutoff wall were written by the extractor but missing from
# the export vocabulary, so the step 0 check refused them as a typo.


def test_every_lake_series_is_a_simulated_series() -> None:
    written = (
        lake_extractor._STATE_QUANTITIES
        | lake_extractor._RATE_QUANTITIES
        | {lake_extractor.CUTOFF_WALL_FLOW}
    ) - {"lak_connection"}
    assert written - set(SIMULATED_SERIES) == set()
    assert export_kind("outlet_inflow") is ExportKind.series
    assert export_kind("cutoff_wall_flow") is ExportKind.series
    assert export_kind("seepage_under_dam") is None
