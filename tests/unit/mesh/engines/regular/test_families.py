"""Line families on the regular grid: the sides, the river chains and the staircase of a contact or a barrier."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from hydromodpy.mesh.cells.barrier_faces import crossed_edges
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.engines.regular.families import _END_SNAP_REL
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import BARRIER_FAMILY, LineFamilySpec, RasterGridSpec
from tests._helpers import reservoir_dam as dam
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_over,
    grid_spec,
    mesh_request,
    planning_inputs,
)

KM_GRID = grid_spec(10, 10, 100.0, crs_wkt=LAMBERT93_WKT)
"""A 1 km square DEM at 100 m: a vertical line at a multiple of 100 m runs on cell faces."""


def _build(grid: RasterGridSpec, *lines: LineFamilySpec) -> PlanarCellMesh:
    return RegularMeshEngine().build(mesh_request(grid, lines=lines))


def _river(*points: tuple[float, float]) -> LineFamilySpec:
    return LineFamilySpec("rivers", "cell", (LineString(points),))


def _contact() -> LineFamilySpec:
    """The contact x = 500 m, drawn northward with the west unit on its left."""
    return LineFamilySpec(
        "geology",
        "face",
        (LineString([(500.0, 0.0), (500.0, 1000.0)]),),
        zone_left=("west_unit",),
        zone_right=("east_unit",),
    )


def _row_of(grid: RasterGridSpec, y: float) -> int:
    """The row of the cells whose band holds *y*; row 0 is north."""
    return int((grid.ymax - y) // grid.dy)


def _left_of(line: LineString, points: np.ndarray) -> np.ndarray:
    """Cross product of each point with the chord of a straight *line*: positive on its left."""
    start, end = np.asarray(line.coords[0]), np.asarray(line.coords[-1])
    chord, offset = end - start, np.asarray(points) - start
    return chord[0] * offset[:, 1] - chord[1] * offset[:, 0]


# --------------------------------------------------------------------------- #
# Sides
# --------------------------------------------------------------------------- #


def test_the_sides_are_boundary_families_with_the_faces_of_the_edge_cells() -> None:
    nrow, ncol = 3, 5
    cell_mesh = _build(grid_spec(nrow, ncol, 200.0, crs_wkt=LAMBERT93_WKT))
    table = cell_mesh.face_families

    west = cell_mesh.face_rows("boundary:west")
    east = cell_mesh.face_rows("boundary:east")
    north = cell_mesh.face_rows("boundary:north")
    south = cell_mesh.face_rows("boundary:south")
    assert sorted(table.cell_a[west]) == list(range(0, nrow * ncol, ncol))
    assert sorted(table.cell_a[east]) == list(range(ncol - 1, nrow * ncol, ncol))
    assert sorted(table.cell_a[north]) == list(range(ncol))
    assert sorted(table.cell_a[south]) == list(range((nrow - 1) * ncol, nrow * ncol))
    assert np.all(table.cell_b[west | east | north | south] == -1)


def test_a_band_of_one_row_has_both_long_sides() -> None:
    grid = grid_spec(1, 40, 100.0, crs_wkt=LAMBERT93_WKT)
    cell_mesh = _build(grid)

    assert cell_mesh.face_rows("boundary:north").sum() == grid.ncol
    assert cell_mesh.face_rows("boundary:south").sum() == grid.ncol
    assert cell_mesh.face_rows("boundary:west").sum() == grid.nrow
    assert cell_mesh.face_rows("boundary:east").sum() == grid.nrow


# --------------------------------------------------------------------------- #
# River chains
# --------------------------------------------------------------------------- #


def test_a_river_along_a_row_is_the_chain_of_that_row_in_line_order() -> None:
    cell_mesh = _build(KM_GRID, _river((5.0, 450.0), (995.0, 450.0)))
    (chain,) = cell_mesh.chains("rivers")
    row = _row_of(KM_GRID, 450.0)

    assert chain.cell_ids.tolist() == list(range(row * KM_GRID.ncol, (row + 1) * KM_GRID.ncol))


def test_the_chain_follows_the_orientation_of_the_line() -> None:
    first = _build(KM_GRID, _river((5.0, 450.0), (995.0, 450.0)))
    second = _build(KM_GRID, _river((995.0, 450.0), (5.0, 450.0)))

    assert (
        second.chains("rivers")[0].cell_ids.tolist()
        == first.chains("rivers")[0].cell_ids.tolist()[::-1]
    )


def test_a_diagonal_river_is_a_continuous_chain_from_corner_to_corner() -> None:
    grid = grid_spec(20, 20, 50.0, crs_wkt=LAMBERT93_WKT)
    cell_mesh = _build(grid, _river((10.0, 990.0), (990.0, 10.0)))
    (chain,) = cell_mesh.chains("rivers")

    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0
    assert chain.cell_ids[0] == 0
    assert chain.cell_ids[-1] == grid.nrow * grid.ncol - 1


@pytest.mark.parametrize(
    "off_the_grid",
    [
        LineString([(5000.0, 5000.0), (6000.0, 5000.0)]),
        LineString([(1050.0, 450.0), (1150.0, 450.0)]),
    ],
    ids=["far_away", "within_two_cells_of_the_edge"],
)
def test_each_line_of_a_river_family_is_one_chain_and_a_line_off_the_grid_gives_none(
    off_the_grid: LineString,
) -> None:
    lines = LineFamilySpec(
        "rivers",
        "cell",
        (
            LineString([(5.0, 450.0), (500.0, 450.0)]),
            LineString([(500.0, 450.0), (995.0, 450.0)]),
            off_the_grid,
        ),
    )
    cell_mesh = _build(KM_GRID, lines)

    assert [chain.chain_id for chain in cell_mesh.chains("rivers")] == [0, 1]


def test_a_river_far_from_the_grid_origin_is_found_in_its_window() -> None:
    grid = grid_spec(119, 135, 25.0, xmin=346512.5, ymin=6789012.25, crs_wkt=LAMBERT93_WKT)
    river = LineString([(347000.0, 6790000.0), (348500.0, 6790900.0)])
    cell_mesh = _build(grid, LineFamilySpec("rivers", "cell", (river,)))
    (chain,) = cell_mesh.chains("rivers")
    crossed = shapely.points(cell_mesh.centers[chain.cell_ids])

    assert shapely.distance(crossed, river).max() <= grid.dx * np.sqrt(2.0) / 2.0
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


# --------------------------------------------------------------------------- #
# Contacts and other face families
# --------------------------------------------------------------------------- #


def test_a_contact_on_cell_faces_is_followed_exactly() -> None:
    cell_mesh = _build(KM_GRID, _contact())
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.face_rows("geology").sum() == KM_GRID.nrow
    assert quality["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)
    assert quality["covered_length_rel"] == pytest.approx(1.0)


@pytest.mark.parametrize("northward", [True, False], ids=["drawn_northward", "drawn_southward"])
def test_the_cell_on_the_left_of_the_contact_comes_first_and_the_zones_follow_the_drawing(
    northward: bool,
) -> None:
    line = LineString([(500.0, 0.0), (500.0, 1000.0)])
    left, right = ("west_unit", "east_unit") if northward else ("east_unit", "west_unit")
    contact = LineFamilySpec(
        "geology",
        "face",
        (line if northward else line.reverse(),),
        zone_left=(left,),
        zone_right=(right,),
    )
    cell_mesh = _build(KM_GRID, contact)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    names = np.array(cell_mesh.zone_names)

    assert np.all((cell_mesh.centers[table.cell_a[rows], 0] < 500.0) == northward)
    assert np.all((cell_mesh.centers[table.cell_b[rows], 0] > 500.0) == northward)
    assert set(names[table.zone_left[rows]]) == {left}
    assert set(names[table.zone_right[rows]]) == {right}


@pytest.mark.parametrize(
    ("grid", "line"),
    [
        (
            grid_spec(20, 40, 0.02, crs_wkt=LAMBERT93_WKT),
            LineString([(0.30, 0.0), (0.50, 0.40)]),
        ),
        (
            grid_spec(20, 20, 500.0, xmin=L93_ORIGIN[0], ymin=L93_ORIGIN[1], crs_wkt=LAMBERT93_WKT),
            LineString(
                [
                    (L93_ORIGIN[0] + 5000.0, L93_ORIGIN[1]),
                    (L93_ORIGIN[0] + 5000.0, L93_ORIGIN[1] + 1e4),
                ]
            ),
        ),
    ],
    ids=["laboratory_sandbox_at_2_cm", "regional_contact_of_10_km_in_lambert_93"],
)
def test_a_contact_far_shorter_or_far_longer_than_a_metre_keeps_the_cell_on_its_left_first(
    grid: RasterGridSpec, line: LineString
) -> None:
    """The side of a face is read along the line at a step that follows the line length."""
    contact = LineFamilySpec("geology", "face", (line,), ("west_unit",), ("east_unit",))
    cell_mesh = _build(grid, contact)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")

    assert rows.sum() >= grid.nrow
    assert np.all(_left_of(line, cell_mesh.centers[table.cell_a[rows]]) > 0.0)
    assert np.all(_left_of(line, cell_mesh.centers[table.cell_b[rows]]) < 0.0)


SNAP_DOMAINS = {
    "north_south_strip": (grid_spec(200, 2, 50.0, crs_wkt=LAMBERT93_WKT), "east_west"),
    "east_west_strip_centred_on_its_origin": (
        grid_spec(2, 200, 50.0, xmin=-5000.0, ymin=-50.0, crs_wkt=LAMBERT93_WKT),
        "north_south",
    ),
    "laboratory_sandbox": (grid_spec(20, 40, 0.02, crs_wkt=LAMBERT93_WKT), "north_south"),
}
"""Domains whose snap tolerance comes from the north-south span, the east-west span or the 1 m floor."""


def _contact_short_of_the_boundary(name: str, share_of_the_tolerance: float) -> PlanarCellMesh:
    """A straight contact across the domain whose two ends stop short of the boundary.

    The gap is a share of the snap tolerance, ``_END_SNAP_REL`` of the larger span
    and never less than ``_END_SNAP_REL`` of a meter: the rounding of a line clipped
    to the domain.
    """
    grid, direction = SNAP_DOMAINS[name]
    width, height = grid.xmax - grid.xmin, grid.ymax - grid.ymin
    gap = share_of_the_tolerance * _END_SNAP_REL * max(width, height, 1.0)
    xmid, ymid = grid.xmin + width / 2.0, grid.ymin + height / 2.0
    if direction == "east_west":
        line = LineString([(grid.xmin + gap, ymid), (grid.xmax - gap, ymid)])
    else:
        line = LineString([(xmid, grid.ymin + gap), (xmid, grid.ymax - gap)])
    return _build(grid, LineFamilySpec("geology", "face", (line,), ("west_unit",), ("east_unit",)))


@pytest.mark.parametrize("name", sorted(SNAP_DOMAINS))
def test_a_contact_that_stops_within_the_snap_tolerance_of_the_boundary_splits_the_domain(
    name: str,
) -> None:
    grid, direction = SNAP_DOMAINS[name]
    cell_mesh = _contact_short_of_the_boundary(name, 0.9)

    crossed = grid.ncol if direction == "east_west" else grid.nrow
    assert cell_mesh.face_rows("geology").sum() == crossed
    assert set(np.array(cell_mesh.zone_names)[cell_mesh.cell_zone]) == {"west_unit", "east_unit"}


@pytest.mark.parametrize("name", sorted(SNAP_DOMAINS))
def test_a_contact_that_stops_beyond_the_snap_tolerance_of_the_boundary_splits_nothing(
    name: str,
) -> None:
    cell_mesh = _contact_short_of_the_boundary(name, 1.5)

    assert not cell_mesh.face_rows("geology").any()


def test_the_cells_take_the_zone_of_their_side_of_the_contact() -> None:
    cell_mesh = _build(KM_GRID, _contact())
    west = cell_mesh.centers[:, 0] < 500.0
    names = np.array(cell_mesh.zone_names)

    assert set(names[cell_mesh.cell_zone[west]]) == {"west_unit"}
    assert set(names[cell_mesh.cell_zone[~west]]) == {"east_unit"}


def test_three_units_parted_by_three_contacts_give_each_cell_its_unit() -> None:
    """Units a (north-west), b (north-east) and c (south); unit a borders two contacts."""
    contacts = LineFamilySpec(
        "geology",
        "face",
        (
            LineString([(0.0, 500.0), (500.0, 500.0)]),
            LineString([(500.0, 500.0), (1000.0, 500.0)]),
            LineString([(500.0, 500.0), (500.0, 1000.0)]),
        ),
        zone_left=("a", "b", "a"),
        zone_right=("c", "c", "b"),
    )
    cell_mesh = _build(KM_GRID, contacts)
    x, y = cell_mesh.centers.T
    names = np.array(cell_mesh.zone_names)[cell_mesh.cell_zone]

    assert sorted(cell_mesh.zone_names) == ["a", "b", "c"]
    assert set(names[(x < 500.0) & (y > 500.0)]) == {"a"}
    assert set(names[(x > 500.0) & (y > 500.0)]) == {"b"}
    assert set(names[y < 500.0]) == {"c"}


def test_a_contact_clipped_to_a_slanted_domain_still_splits_it() -> None:
    x0, y0 = L93_ORIGIN
    corners = [(0.0, 137.3), (913.7, 0.0), (1000.1, 871.9), (77.7, 1013.3)]
    domain = shapely.Polygon([(x0 + x, y0 + y) for x, y in corners])
    trace = LineString([(x0 + 300.0, y0 - 300.0), (x0 + 700.0, y0 + 1300.0)])
    contact = LineFamilySpec(
        "geology",
        "face",
        (domain.intersection(trace),),
        zone_left=("west_unit",),
        zone_right=("east_unit",),
    )
    grid = grid_spec(21, 21, 50.0, xmin=x0, ymin=y0, crs_wkt=LAMBERT93_WKT)
    request = dataclasses.replace(mesh_request(grid, lines=(contact,)), domain=domain)
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.face_rows("geology").sum() > 0
    assert cell_mesh.cell_zone is not None
    inside = shapely.intersects(domain, shapely.points(cell_mesh.centers))
    x, y = (cell_mesh.centers - [x0 + 300.0, y0 - 300.0]).T
    west = 1600.0 * x - 400.0 * y < 0.0
    names = np.array(cell_mesh.zone_names)
    assert set(names[cell_mesh.cell_zone[inside & west]]) == {"west_unit"}
    assert set(names[cell_mesh.cell_zone[inside & ~west]]) == {"east_unit"}


def test_a_contact_between_faces_becomes_a_staircase_the_report_measures() -> None:
    slanted = LineFamilySpec("geology", "face", (LineString([(0.0, 0.0), (1000.0, 1000.0)]),))
    cell_mesh = _build(KM_GRID, slanted)
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.cell_zone is None
    assert quality["hausdorff_m"] > 0.0
    assert quality["hausdorff_m"] <= KM_GRID.dx * np.sqrt(2.0)


def test_a_closed_ring_labels_the_cells_it_holds() -> None:
    ring = shapely.Polygon([(300, 300), (700, 300), (700, 700), (300, 700)]).exterior
    lake = LineFamilySpec("lakes", "face", (LineString(ring.coords),), closed=True)
    cell_mesh = _build(KM_GRID, lake)

    assert cell_mesh.face_rows("lakes").sum() == ring.length / KM_GRID.dx
    assert cell_mesh.qa.families["lakes"]["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)


def test_a_face_line_that_splits_no_cell_gives_no_face() -> None:
    """A short contact inside one cell closes no polygon, so no face lies between two labels."""
    inside_one_cell = LineFamilySpec(
        "geology", "face", (LineString([(420.0, 430.0), (460.0, 470.0)]),), ("a",), ("b",)
    )
    cell_mesh = _build(KM_GRID, inside_one_cell)

    assert not cell_mesh.face_rows("geology").any()
    assert cell_mesh.cell_zone is None


def test_a_barrier_takes_the_faces_whose_two_centres_lie_across_it() -> None:
    """A wall that ends inside the domain splits no polygon: its faces are the ones it crosses."""
    wall = LineString([(500.0, 0.0), (500.0, 620.0)])
    cell_mesh = _build(KM_GRID, LineFamilySpec(BARRIER_FAMILY, "face", (wall,)))
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(BARRIER_FAMILY)
    first = cell_mesh.centers[table.cell_a[rows]]
    second = cell_mesh.centers[table.cell_b[rows]]
    rows_below_the_wall_end = int((np.unique(cell_mesh.centers[:, 1]) < 620.0).sum())

    assert rows.sum() == rows_below_the_wall_end
    assert np.all(first[:, 0] < 500.0)
    assert np.all(second[:, 0] > 500.0)
    assert np.all(first[:, 1] == second[:, 1])


def test_the_regular_staircase_is_the_faces_the_barrier_crosses() -> None:
    """A barrier the planner passes on takes the faces whose two centers it separates."""
    barrier = LineString([(dam.X0 + 210.0, dam.Y0 + 110.0), (dam.X0 + 830.0, dam.Y0 + 590.0)])
    inputs = planning_inputs(
        grid_over(dam.DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        watershed=dam.DOMAIN,
        synthetic=False,
        barriers=(barrier,),
    )
    request = plan_mesh_request(MeshConfig(engine="regular", cell_size=40.0), inputs)
    cell_mesh = RegularMeshEngine().build(request)
    geometry = cell_mesh.geometry
    stairs = {
        tuple(pair)
        for pair in geometry.edge_cells[
            crossed_edges(geometry, cell_mesh.centers, barrier)
        ].tolist()
    }
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows(BARRIER_FAMILY) & (table.cell_b >= 0)
    barred = np.sort(np.column_stack([table.cell_a[rows], table.cell_b[rows]]), axis=1)

    assert {tuple(pair) for pair in barred.tolist()} == stairs
    assert len(stairs) > 10
