"""The planner adds the barrier family and welds its shore stretch to the lake ring.

A cutoff wall is laid on the lake shore between its two wings, so that stretch
is a line of both families. The planner cuts the wall where it leaves the ring,
resamples the pieces off it, and puts the wall back together with the
resampled ring vertices: the engine meshes the stretch once. A wing no cell
resolves is left out, and a staircase engine gets the raw wall.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planning.barrier_lines import RING_FAMILY, split_barriers
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import BARRIER_FAMILY, LineFamilySpec, MeshRequest
from hydromodpy.model.boundaries.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
from tests._helpers.mesh_cases import grid_over, planning_inputs
from tests._helpers.reservoir_dam import DOMAIN, reservoir, trace

pytestmark = pytest.mark.usefixtures("builtin_engines")

GRADED = {"engine": "voronoi", "cell_size": 60.0, "lake_refinement": {"cell_size": 30.0}}


def _inputs(barriers: tuple[LineString, ...], *, lakes: tuple = ()) -> PlanningInputs:
    return planning_inputs(
        grid_over(DOMAIN, 10.0),
        domain=DOMAIN,
        watershed=DOMAIN,
        lakes=lakes,
        barriers=barriers,
        synthetic=False,
    )


def _walled(offset: float, mesh: dict) -> tuple[SnappedWall, MeshRequest]:
    wall = snap_wall_to_shore(reservoir(), trace(offset), 50.0)
    request = plan_mesh_request(
        MeshConfig.model_validate(mesh), _inputs((wall.line,), lakes=(wall.polygon,))
    )
    return wall, request


def test_the_switch_set_to_none_leaves_the_barriers_out() -> None:
    _, request = _walled(12.0, {**GRADED, "families": {"barriers": "none"}})

    assert request.family(BARRIER_FAMILY) is None
    assert request.family("lakes") is not None


_RING = LineString([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)])
_TOL = 1.0e-6


def _families(*barriers: LineString, ring: LineString = _RING) -> tuple[LineFamilySpec, ...]:
    return (
        LineFamilySpec(RING_FAMILY, "face", (ring,), closed=ring.is_closed),
        LineFamilySpec(BARRIER_FAMILY, "face", barriers),
    )


def test_a_barrier_off_every_ring_is_left_as_it_is() -> None:
    families = _families(LineString([(200.0, 0.0), (300.0, 50.0)]))

    split = split_barriers(families, _TOL)

    assert split.families == families
    assert split.fixed_points.shape == (0, 2)
    assert split.welded(families) == families


def test_a_wall_laid_wholly_on_the_shore_is_the_ring_stretch_once_welded() -> None:
    """No piece lies off the ring, so the barrier family holds no line until the weld."""
    wall = LineString([(100.0, 20.0), (100.0, 100.0), (60.0, 100.0)])

    split = split_barriers(_families(wall), _TOL)

    assert [family.name for family in split.families] == [RING_FAMILY]
    np.testing.assert_array_equal(split.fixed_points, [[100.0, 20.0], [60.0, 100.0]])
    ring = LineString([(0, 0), (100, 0), (100, 20), (100, 100), (60, 100), (0, 100), (0, 0)])
    welded = split.welded((LineFamilySpec(RING_FAMILY, "face", (ring,), closed=True),))
    (barrier,) = (family for family in welded if family.name == BARRIER_FAMILY)
    assert list(barrier.lines[0].coords) == [(100.0, 20.0), (100.0, 100.0), (60.0, 100.0)]


@pytest.mark.parametrize("along", [True, False], ids=["along the line", "against the line"])
def test_a_wall_on_a_shore_cut_open_by_the_domain_follows_its_vertices(along: bool) -> None:
    """A lake ring the domain outline cuts is an open line: the stretch runs one way along it."""
    shore = LineString([(0.0, 0.0), (50.0, 0.0), (100.0, 0.0), (150.0, 0.0)])
    wall = LineString([(50.0, -40.0), (50.0, 0.0), (100.0, 0.0), (100.0, -40.0)])
    if not along:
        wall = wall.reverse()

    split = split_barriers(_families(wall, ring=shore), _TOL)
    welded = split.welded(_families(*split.families[-1].lines, ring=shore))

    (barrier,) = (family for family in welded if family.name == BARRIER_FAMILY)
    assert list(barrier.lines[0].coords) == list(wall.coords)


def test_a_ring_that_lost_a_stretch_end_cannot_be_welded() -> None:
    wall = LineString([(100.0, 20.0), (100.0, 80.0), (140.0, 80.0)])
    split = split_barriers(_families(wall), _TOL)
    pieces = next(family for family in split.families if family.name == BARRIER_FAMILY)

    # The weld fails loudly whether it raises ValueError or MeshRequestError.
    with pytest.raises((ValueError, MeshRequestError), match="nearest vertex of the resampled"):
        split.welded((*_families(ring=_RING)[:1], pieces))


@pytest.mark.parametrize("reverse", [False, True], ids=["short first", "short last"])
def test_a_wing_shorter_than_the_local_cell_is_left_out_at_either_end(reverse: bool) -> None:
    """A 20 m wing and a 60 m wing off the shore, against a 50 m local cell."""
    wall = LineString([(120.0, 20.0), (100.0, 20.0), (100.0, 80.0), (160.0, 80.0)])
    if reverse:
        wall = wall.reverse()

    split = split_barriers(_families(wall), _TOL, shortest=lambda xy: np.full(len(xy), 50.0))

    (barrier,) = (family for family in split.families if family.name == BARRIER_FAMILY)
    assert len(barrier.lines) == 1
    assert barrier.lines[0].length == pytest.approx(60.0)
