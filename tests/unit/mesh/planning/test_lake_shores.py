"""A generated Voronoi mesh follows each lake shore at its cell size, and closes it.

The mesh lays one mirror pair on each shore segment. A river chain in the lake,
an arm narrower than a cell, or a wall wing of a few meters take or shrink those
pairs and open the lake regions. The planner keeps the rivers half a river cell
off the lakes, gives the mesh the shore smoothed at the cell scale, and leaves
out a wall wing no cell resolves. A cell of an arm left out still joins its
lake when the lake covers most of it. Two lakes, or two lobes of one lake,
closer than the smoothing allows are drawn apart, and a lake too narrow for
any cell keeps its own outline.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.solver.modflow6.builders._lake_geometry import interior_cells, polygon_overlap
from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.engines.voronoi.from_seeds import CLOSED_SHORE_SHARE
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.planning import families
from hydromodpy.spatial.mesh.planning.families import RIVER_MARGIN_SHARE
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.lake_shores import (
    LAKE_SHORE_SHARE,
    FollowedShores,
    followed_lake_shores,
)
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY
from tests._helpers.mesh_cases import L93_ORIGIN, grid_over, planning_inputs

pytestmark = pytest.mark.usefixtures("builtin_engines")

X0, Y0 = L93_ORIGIN
_DOMAIN = box(X0, Y0, X0 + 1600.0, Y0 + 1000.0)
_GRID = grid_over(_DOMAIN, 10.0)
_BODY = box(X0 + 400.0, Y0 + 350.0, X0 + 1100.0, Y0 + 650.0)
_ARM = box(X0 + 1100.0, Y0 + 494.0, X0 + 1400.0, Y0 + 506.0)
_RIVER = LineString([(X0, Y0 + 480.0), (X0 + 1600.0, Y0 + 520.0)])
_CONFIG = MeshConfig(
    engine="voronoi", cell_size=60.0, river_cell_size=30.0, lake_refinement={"cell_size": 30.0}
)


def _inputs(lake: Polygon, *, river: bool = False, barriers=()) -> PlanningInputs:
    return planning_inputs(
        _GRID,
        domain=_DOMAIN,
        river_trace=SimpleNamespace(lines=(_RIVER,)) if river else None,
        lakes=(lake,),
        barriers=tuple(barriers),
    )


@pytest.fixture
def followed(monkeypatch: pytest.MonkeyPatch) -> list[FollowedShores]:
    """The shores the planner picks, in order, as it computed them."""
    picked: list[FollowedShores] = []

    def record(*args: object, **kwargs: object) -> FollowedShores:
        picked.append(followed_lake_shores(*args, **kwargs))
        return picked[-1]

    monkeypatch.setattr(families, "followed_lake_shores", record)
    return picked


def _build(inputs: PlanningInputs, config: MeshConfig = _CONFIG):
    request = plan_mesh_request(config, inputs)
    return request, VoronoiMeshEngine().build(request)


def _family(request, name: str):
    return next(family for family in request.lines if family.name == name)


def test_a_river_through_the_lake_leaves_the_shore_closed() -> None:
    request, mesh = _build(_inputs(_BODY, river=True))

    rivers = shapely.multilinestrings(list(_family(request, "rivers").lines))
    assert not rivers.intersects(_BODY.buffer(0.5 * RIVER_MARGIN_SHARE * 30.0))
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert mesh.chains("rivers")


def test_an_arm_narrower_than_a_cell_is_left_out_and_the_shore_closes(
    followed: list[FollowedShores],
) -> None:
    lake = _BODY.union(_ARM)
    request, mesh = _build(_inputs(lake))

    ring = shapely.multilinestrings(list(_family(request, "lakes").lines))
    assert ring.distance(shapely.Point(X0 + 1350.0, Y0 + 500.0)) > 100.0
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    (shores,) = followed
    assert shores.left_out_m2[0] > 0.0
    assert shores.notes() and set(shores.notes()) <= set(request.notes)


def test_the_cells_of_an_arm_left_out_join_the_lake_when_it_covers_most_of_them() -> None:
    lake = _BODY.union(box(X0 + 1100.0, Y0 + 480.0, X0 + 1400.0, Y0 + 520.0))
    _, mesh = _build(_inputs(lake))
    cells = interior_cells(mesh, "lakes", lake)
    overlap_cells, overlap = polygon_overlap(mesh, lake)
    share = np.zeros(mesh.n_cells)
    share[overlap_cells] = overlap / mesh.geometry.areas[overlap_cells]
    centres = shapely.points(mesh.centers[cells])

    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert np.any(shapely.contains(box(X0 + 1150.0, Y0 + 470.0, X0 + 1400.0, Y0 + 530.0), centres))
    majority = np.flatnonzero(share > 0.5)
    assert set(majority.tolist()) <= set(cells.tolist())
    footprint = mesh.geometry.areas[cells].sum() / lake.area
    assert 0.9 <= footprint <= 1.1


def test_a_lake_with_no_narrow_part_keeps_its_own_outline(
    followed: list[FollowedShores],
) -> None:
    request, mesh = _build(_inputs(_BODY))

    ring = shapely.multilinestrings(list(_family(request, "lakes").lines))
    vertices = shapely.points(shapely.get_coordinates(ring))
    assert shapely.distance(vertices, _BODY.boundary).max() <= 1e-6
    (shores,) = followed
    assert (shores.left_out_m2, shores.taken_in_m2) == ((0.0,), (0.0,))
    assert shores.notes() == ()
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE


def test_a_wall_wing_of_a_few_metres_is_left_out_and_the_wall_stays_on_the_shore() -> None:
    top = Y0 + 650.0
    wall = LineString(
        [
            (X0 + 1100.0 + 5.0, top + 3.0),
            (X0 + 1100.0, top),
            (X0 + 700.0, top),
            (X0 + 600.0, top + 100.0),
        ]
    )
    request, mesh = _build(_inputs(_BODY, barriers=(wall,)))

    line = _family(request, BARRIER_FAMILY).lines[0]
    ends = shapely.get_coordinates(line)[[0, -1]]
    assert np.allclose(ends[0], (X0 + 1100.0, top))
    assert np.allclose(ends[-1], (X0 + 600.0, top + 100.0))
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert mesh.qa.families[BARRIER_FAMILY]["covered_length_rel"] >= CLOSED_SHORE_SHARE


def test_one_seed_gives_one_mesh_with_lakes_and_rivers() -> None:
    inputs = _inputs(_BODY.union(_ARM), river=True)
    _, first = _build(inputs)
    _, second = _build(inputs)

    assert np.array_equal(np.asarray(first.mesh.vertices), np.asarray(second.mesh.vertices))
    assert np.array_equal(first.centers, second.centers)


_CELL = 30.0
_RADIUS = LAKE_SHORE_SHARE * _CELL
_APART = 0.95 * 2.0 * _RADIUS
"""Two parts drawn apart lie two radii apart, less the sag of buffers drawn with few segments."""


def _shores(*lakes: Polygon) -> FollowedShores:
    return followed_lake_shores(lakes, lambda xy: np.full(len(xy), _CELL), finest=_CELL)


def test_a_later_lake_closer_than_the_smoothing_gives_up_the_strip_next_to_the_earlier() -> None:
    first, second = box(0.0, 0.0, 200.0, 200.0), box(220.0, 0.0, 420.0, 200.0)

    shores = _shores(first, second)

    assert shores.polygons[0].equals(first)
    assert shores.left_out_m2[1] > 0.0
    assert shores.polygons[1].distance(shores.polygons[0]) >= _APART


def test_two_lobes_that_meet_at_a_corner_are_drawn_apart() -> None:
    """A thin strip joins two square lobes 6 m apart at their corners: the smaller lobe gives way."""
    gap = 6.0
    lake = shapely.union_all(
        [
            box(0.0, 0.0, 200.0, 200.0),
            box(200.0 + gap, 200.0 + gap, 400.0 + gap, 400.0 + gap),
            LineString([(190.0, 190.0), (210.0 + gap, 210.0 + gap)]).buffer(3.0),
        ]
    )

    (followed,) = _shores(lake).polygons

    parts = shapely.get_parts(followed)
    assert len(parts) == 2
    assert parts[0].distance(parts[1]) >= _APART


def test_a_lake_narrower_than_the_smoothing_keeps_its_own_outline() -> None:
    """Its smoothed outline vanishes, so it neither changes nor pushes the next lake away."""
    thin, wide = box(0.0, 0.0, 500.0, 10.0), box(0.0, 30.0, 300.0, 330.0)

    shores = _shores(thin, wide)

    assert shores.polygons[0].equals(thin)
    assert shores.left_out_m2[0] == 0.0
    assert shores.polygons[1].equals(wide)


def test_a_small_lobe_near_a_large_one_gives_way_to_it_whole() -> None:
    """Thin strips join three lobes: the small one lies within reach of a large one and goes."""
    large = box(0.0, 0.0, 200.0, 200.0)
    far = box(500.0, 0.0, 650.0, 150.0)
    small = box(206.0, 206.0, 246.0, 246.0)
    strips = [
        LineString([(190.0, 190.0), (216.0, 216.0)]).buffer(3.0),
        LineString([(190.0, 100.0), (510.0, 100.0)]).buffer(3.0),
    ]
    lake = shapely.union_all([large, far, small, *strips])

    shores = _shores(lake)

    (followed,) = shores.polygons
    assert len(shapely.get_parts(followed)) == 2
    assert not followed.intersects(small)
    assert shores.left_out_m2[0] >= small.area
