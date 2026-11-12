"""Line families on the regular grid: the sides, the river chains and the staircase of a contact or a barrier."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.engines.regular.families import _END_SNAP_REL
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import LineFamilySpec, RasterGridSpec
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, mesh_request

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


# --------------------------------------------------------------------------- #
# River chains
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Contacts and other face families
# --------------------------------------------------------------------------- #


def test_a_contact_on_cell_faces_is_followed_exactly() -> None:
    cell_mesh = _build(KM_GRID, _contact())
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.face_rows("geology").sum() == KM_GRID.nrow
    assert quality["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)
    assert quality["covered_length_rel"] == pytest.approx(1.0)


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
def test_a_contact_that_stops_beyond_the_snap_tolerance_of_the_boundary_splits_nothing(
    name: str,
) -> None:
    cell_mesh = _contact_short_of_the_boundary(name, 1.5)

    assert not cell_mesh.face_rows("geology").any()


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
