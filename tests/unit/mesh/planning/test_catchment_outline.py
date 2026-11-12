"""The planner smooths the staircase of the catchment outline where the mesh follows it.

A catchment delineated on the DEM has an outline of pixel steps. A graded engine
that follows it, as the ``watershed_boundary`` face family or as the domain
outline, would follow every step. The planner cuts each corner of a step at half
a pixel and simplifies the line at half a pixel, so the new outline stays within
a pixel of the staircase and keeps the area. A river end, a barrier end or a
lake shore that touched the outline still touches it, and so does the outlet of
the catchment, with or without a river family to carry it. The planner hands
the outline it smoothed to the mesh step, which gives it to the solver
(``smoothed_catchment``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pytest
import shapely
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape

from hydromodpy.catchment.algorithms.river_mesh_trace import RiverMeshTrace
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planning import catchment_outline
from hydromodpy.mesh.planning.catchment_outline import (
    OUTLINE_CUT_SHARE,
    smooth_catchment,
    smooth_polygon,
)
from hydromodpy.mesh.planning.geometry_cleanup import CLEANUP_PIXEL_SHARE, GeometryCleanup
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import BARRIER_FAMILY
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import L93_ORIGIN, grid_spec, planning_inputs, square_domain

pytestmark = pytest.mark.usefixtures("builtin_engines")

X0, Y0 = L93_ORIGIN
_PIXEL = 10.0
_DOMAIN = square_domain(1000.0, x0=X0, y0=Y0)
_GRID = grid_spec(100, 100, _PIXEL, xmin=X0, ymin=Y0)
_FACE = {"watershed_boundary": "face"}


def _staircase(radius: float = 300.0, hole_radius: float = 0.0) -> Polygon:
    """An elliptic catchment as a delineation draws it: the polygon of a pixel mask."""
    rows, cols = np.mgrid[0:100, 0:100]
    x = (cols + 0.5) * _PIXEL - 480.0
    y = (100 - rows - 0.5) * _PIXEL - 520.0
    mask = np.hypot(x, 0.8 * y) < radius
    if hole_radius:
        mask &= np.hypot(x - 40.0, y + 30.0) >= hole_radius
    transform = Affine(_PIXEL, 0.0, X0, 0.0, -_PIXEL, Y0 + 1000.0)
    parts = [
        shape(geometry)
        for geometry, value in shapes(
            mask.astype("uint8"), mask=mask, transform=transform, connectivity=4
        )
        if value == 1
    ]
    return max(parts, key=lambda part: part.area)


def _xy(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


def _inputs(
    watershed: Polygon,
    *,
    domain: Polygon = _DOMAIN,
    rivers=(),
    barriers=(),
    lakes=(),
) -> PlanningInputs:
    trace = (
        RiverMeshTrace(source_kind="file", crs_wkt=TEST_CRS_WKT, lines=tuple(rivers))
        if rivers
        else None
    )
    return planning_inputs(
        _GRID,
        domain=domain,
        river_trace=trace,
        watershed=watershed,
        lakes=tuple(lakes),
        barriers=tuple(barriers),
        synthetic=False,
    )


def _config(engine: str = "voronoi", **families: str) -> MeshConfig:
    return MeshConfig(engine=engine, cell_size=40.0, families=families)


def _smoothed(inputs: PlanningInputs, config: MeshConfig) -> tuple[PlanningInputs, GeometryCleanup]:
    """The inputs after the smoothing alone, as the planner smooths them first, and its record."""
    cleanup = GeometryCleanup(tolerance=CLEANUP_PIXEL_SHARE * _PIXEL)
    return smooth_catchment(inputs, config.families, cleanup, _PIXEL), cleanup


def _distance(first, second) -> float:
    """Largest distance from the vertices of one outline to the other, both ways."""
    return max(
        float(shapely.distance(second, shapely.points(shapely.get_coordinates(first))).max()),
        float(shapely.distance(first, shapely.points(shapely.get_coordinates(second))).max()),
    )


def _diagonal_staircase(steps: int) -> Polygon:
    """The pixels of a right triangle: legs of ``steps`` pixels, a one-pixel staircase for the slope."""
    p = _PIXEL
    ring = [(0.0, 0.0), (steps * p, 0.0), (steps * p, steps * p)]
    for k in range(steps, 0, -1):
        ring.extend([((k - 1) * p, k * p), ((k - 1) * p, (k - 1) * p)])
    return Polygon([_xy(x, y) for x, y in ring])


def test_diagonal_staircase() -> None:
    stair = _diagonal_staircase(20)

    smooth = smooth_polygon(stair, _PIXEL)

    assert smooth is not None
    coords = np.asarray(smooth.exterior.coords) - np.array([X0, Y0])
    slope = coords[(coords[:, 0] < 200.0) & (coords[:, 1] > 0.0) & (coords[:, 1] > coords[:, 0])]
    assert len(smooth.exterior.coords) <= 6
    assert len(slope) >= 2
    assert np.allclose(slope[:, 1] - slope[:, 0], OUTLINE_CUT_SHARE * _PIXEL)
    assert _distance(stair.exterior, smooth.exterior) <= _PIXEL


@pytest.mark.parametrize(
    "polygon",
    [
        MultiPolygon([box(*_xy(0, 0), *_xy(30, 20)), box(*_xy(100, 0), *_xy(130, 20))]),
        Polygon(),
        Polygon([_xy(0, 0), _xy(_PIXEL, 0), _xy(_PIXEL, _PIXEL)]),
    ],
    ids=["two parts", "empty", "half pixel"],
)
def test_unsmoothable_polygon_unchanged(polygon) -> None:
    """Two parts or an empty polygon are no catchment outline, and a triangle has no step."""
    assert smooth_polygon(polygon, _PIXEL) is polygon


def test_long_edge_corner_stays() -> None:
    """A square with a staircase for its top right corner: the other three corners stay."""
    p = _PIXEL
    ring = [(0.0, 0.0), (300.0, 0.0), (300.0, 200.0)]
    for k in range(10):
        ring.extend([(300.0 - k * p - p, 200.0 + k * p), (300.0 - k * p - p, 200.0 + k * p + p)])
    ring.extend([(0.0, 300.0)])
    stair = Polygon([_xy(x, y) for x, y in ring])
    assert stair.is_valid

    smooth = smooth_polygon(stair, _PIXEL)

    assert smooth is not None
    vertices = {tuple(np.round(xy, 6)) for xy in smooth.exterior.coords}
    for corner in ((0.0, 0.0), (300.0, 0.0), (0.0, 300.0)):
        assert tuple(np.round(_xy(*corner), 6)) in vertices
    assert smooth.area < stair.area + p * p
    assert len(smooth.exterior.coords) < len(stair.exterior.coords)


_CENTRE = np.array(_xy(480.0, 520.0))


def _pulled_off_corner(stair: Polygon, index: int) -> tuple[float, float]:
    """A vertex of the staircase that the smoothing alone would leave more than a quarter pixel off."""
    smooth = smooth_polygon(stair, _PIXEL)
    coords = np.asarray(stair.exterior.coords)
    gap = shapely.distance(smooth.exterior, shapely.points(coords))
    candidates = np.flatnonzero(gap > 0.25 * _PIXEL)
    return tuple(coords[candidates[index % len(candidates)]])


def _inward(point: tuple[float, float], length: float) -> np.ndarray:
    """The point *length* meters from *point* toward the middle of the catchment."""
    toward = _CENTRE - np.array(point)
    return np.array(point) + length * toward / np.hypot(*toward)


def _on_outline(request, point: tuple[float, float]) -> float:
    """Distance from *point* to the catchment ring the request follows."""
    return float(
        shapely.union_all(request.family("watershed_boundary").lines).distance(Point(point))
    )


_Anchor = tuple[PlanningInputs, tuple[float, float], str, int | None]
"""The inputs, the point on the staircase, the family that touches it and the index of its end there."""


def _river_at_the_outlet(stair: Polygon, domain: Polygon = _DOMAIN) -> _Anchor:
    """The main river ends on the staircase, at its outlet."""
    outlet = _pulled_off_corner(stair, 7)
    river = LineString([tuple(_inward(outlet, 200.0)), outlet])
    return _inputs(stair, domain=domain, rivers=(river,)), outlet, "rivers", -1


def _river_at_the_outlet_of_a_catchment_domain(stair: Polygon) -> _Anchor:
    return _river_at_the_outlet(stair, domain=stair)


def _river_ending_in_the_middle_of_a_step(stair: Polygon) -> _Anchor:
    coords = np.asarray(stair.exterior.coords)
    middles = 0.5 * (coords[:-1] + coords[1:])
    smooth = smooth_polygon(stair, _PIXEL)
    off = np.flatnonzero(shapely.distance(smooth.exterior, shapely.points(middles)) > 0.25 * _PIXEL)
    end = tuple(middles[off[len(off) // 3]])
    river = LineString([tuple(_inward(end, 150.0)), end])
    return _inputs(stair, rivers=(river,)), end, "rivers", -1


def _barrier_starting_on_the_outline(stair: Polygon) -> _Anchor:
    start = _pulled_off_corner(stair, 11)
    wall = LineString([start, tuple(_inward(start, 120.0))])
    return _inputs(stair, barriers=(wall,)), start, BARRIER_FAMILY, 0


def _lake_touching_the_outline(stair: Polygon) -> _Anchor:
    tip = _pulled_off_corner(stair, 2)
    middle = _inward(tip, 80.0)
    side = np.array([-(_CENTRE - np.array(tip))[1], (_CENTRE - np.array(tip))[0]])
    side = 25.0 * side / np.hypot(*side)
    lake = Polygon([tip, tuple(middle + side), tuple(middle - side)])
    assert lake.is_valid
    assert lake.distance(stair.exterior) < 1.0e-9
    return _inputs(stair, lakes=(lake,)), tip, "lakes", None


_ANCHORS: dict[str, Callable[[Polygon], _Anchor]] = {
    "river end at the outlet": _river_at_the_outlet,
    "river end at the outlet of a catchment domain": _river_at_the_outlet_of_a_catchment_domain,
    "river end in the middle of a step": _river_ending_in_the_middle_of_a_step,
    "barrier end": _barrier_starting_on_the_outline,
    "lake tip": _lake_touching_the_outline,
}


@pytest.mark.parametrize("anchor", list(_ANCHORS))
def test_touching_line_stays_touching(anchor: str) -> None:
    """The smoothing alone would leave the point more than a quarter pixel off the outline."""
    stair = _staircase()
    inputs, point, family, end = _ANCHORS[anchor](stair)

    request = plan_mesh_request(_config(**_FACE), inputs)

    lines = request.family(family).lines
    if end is None:
        touching = point
        assert shapely.union_all(lines).distance(Point(point)) < 1.0e-6
    else:
        touching = lines[0].coords[end]
        assert Point(touching).distance(Point(point)) < 1.0e-6
    assert _on_outline(request, touching) < 1.0e-6


def test_outlet_without_river_family() -> None:
    stair = _staircase()
    outlet = _pulled_off_corner(stair, 7)
    inputs = replace(_inputs(stair, domain=stair), outlet=Point(outlet))

    request = plan_mesh_request(_config(rivers="none", **_FACE), inputs)

    assert request.family("rivers") is None
    assert request.domain.exterior.distance(Point(outlet)) < 1.0e-6
    assert _on_outline(request, outlet) < 1.0e-6


def test_outlet_off_outline() -> None:
    stair = _staircase()
    inside = tuple(_inward(_pulled_off_corner(stair, 7), 5.0 * _PIXEL))
    config = _config(rivers="none", **_FACE)
    inputs = _inputs(stair)

    kept, _ = _smoothed(replace(inputs, outlet=Point(inside)), config)

    assert kept.watershed.equals(_smoothed(inputs, config)[0].watershed)


def test_close_points_pin_one_vertex() -> None:
    """Two line ends half a tolerance apart on a step: the first is a vertex, the second stays near."""
    stair = _staircase()
    coords = np.asarray(stair.exterior.coords)
    middles = 0.5 * (coords[:-1] + coords[1:])
    smooth = smooth_polygon(stair, _PIXEL)
    off = np.flatnonzero(shapely.distance(smooth.exterior, shapely.points(middles)) > 0.25 * _PIXEL)
    index = off[len(off) // 3]
    along = (coords[index + 1] - coords[index]) / np.hypot(*(coords[index + 1] - coords[index]))
    first = middles[index]
    second = first + 0.5 * CLEANUP_PIXEL_SHARE * _PIXEL * along

    pinned = smooth_polygon(stair, _PIXEL, [Point(first), Point(second)])

    assert pinned is not None
    assert pinned.exterior.distance(Point(first)) < 1.0e-6
    assert pinned.exterior.distance(Point(second)) <= CLEANUP_PIXEL_SHARE * _PIXEL


def test_invalid_smoothing_keeps_staircase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stair = _staircase()
    bow_tie = np.array([_xy(0, 0), _xy(100, 100), _xy(100, 0), _xy(0, 100), _xy(0, 0)])
    monkeypatch.setattr(catchment_outline, "_smoothed_ring", lambda *args: bow_tie)

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, domain=stair))

    assert request.domain is stair
    assert (
        len(request.family("watershed_boundary").lines[0].coords) >= len(stair.exterior.coords) - 1
    )
    stayed = GeometryCleanup(
        tolerance=CLEANUP_PIXEL_SHARE * _PIXEL, unsmoothed=["catchment and domain"]
    )
    assert stayed.notes()
    assert set(stayed.notes()) <= set(request.notes)
