"""The planner smooths the staircase of the catchment outline where the mesh follows it.

A catchment delineated on the DEM has an outline of pixel steps. A graded engine
that follows it, as the ``watershed_boundary`` face family or as the domain
outline, would follow every step. The planner cuts each corner of a step at half
a pixel and simplifies the line at half a pixel, so the new outline stays within
a pixel of the staircase and keeps the area. A river end, a barrier end or a
lake shore that touched the outline still touches it.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
import shapely
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import LineString, Point, Polygon, box, shape

from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.planning import catchment_outline
from hydromodpy.spatial.mesh.planning.catchment_outline import smooth_polygon
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import RasterGridSpec

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 330_000.0, 6_780_000.0
_PIXEL = 10.0
_DOMAIN = box(X0, Y0, X0 + 1000.0, Y0 + 1000.0)
_GRID = RasterGridSpec(
    xmin=X0,
    xmax=X0 + 1000.0,
    ymin=Y0,
    ymax=Y0 + 1000.0,
    dx=_PIXEL,
    dy=_PIXEL,
    nrow=100,
    ncol=100,
    crs_wkt=_WKT,
)
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
        RiverMeshTrace(source_kind="file", crs_wkt=_WKT, lines=tuple(rivers)) if rivers else None
    )
    return PlanningInputs(
        dem_grid=_GRID,
        crs_wkt=_WKT,
        domain=domain,
        river_trace=trace,
        watershed=watershed,
        lakes=tuple(lakes),
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
        barriers=tuple(barriers),
    )


def _config(engine: str = "voronoi", **families: str) -> MeshConfig:
    return MeshConfig(engine=engine, cell_size=40.0, families=families)


def _distance(first, second) -> float:
    """Largest distance from the vertices of one outline to the other, both ways."""
    return max(
        float(shapely.distance(second, shapely.points(shapely.get_coordinates(first))).max()),
        float(shapely.distance(first, shapely.points(shapely.get_coordinates(second))).max()),
    )


def test_a_staircase_is_smoothed_within_a_pixel_and_keeps_its_area() -> None:
    stair = _staircase()

    smooth = smooth_polygon(stair, _PIXEL)

    assert smooth is not None
    assert smooth.is_valid
    assert len(smooth.exterior.coords) < 0.5 * len(stair.exterior.coords)
    assert _distance(stair.exterior, smooth.exterior) <= _PIXEL
    assert shapely.hausdorff_distance(stair.exterior, smooth.exterior, densify=0.05) <= _PIXEL
    assert abs(smooth.area - stair.area) / stair.area < 0.005


def test_a_hole_of_the_catchment_is_smoothed_like_its_outline() -> None:
    stair = _staircase(hole_radius=60.0)
    assert len(stair.interiors) == 1

    smooth = smooth_polygon(stair, _PIXEL)

    assert smooth is not None
    assert smooth.is_valid
    assert len(smooth.interiors) == 1
    assert len(smooth.interiors[0].coords) < len(stair.interiors[0].coords)
    assert _distance(stair.interiors[0], smooth.interiors[0]) <= _PIXEL


def _diagonal_staircase(steps: int) -> Polygon:
    """The pixels of a right triangle: legs of ``steps`` pixels, a one-pixel staircase for the slope."""
    p = _PIXEL
    ring = [(0.0, 0.0), (steps * p, 0.0), (steps * p, steps * p)]
    for k in range(steps, 0, -1):
        ring.extend([((k - 1) * p, k * p), ((k - 1) * p, (k - 1) * p)])
    return Polygon([_xy(x, y) for x, y in ring])


def test_a_diagonal_staircase_falls_on_its_middle_line() -> None:
    stair = _diagonal_staircase(20)

    smooth = smooth_polygon(stair, _PIXEL)

    assert smooth is not None
    coords = np.asarray(smooth.exterior.coords) - np.array([X0, Y0])
    slope = coords[(coords[:, 0] < 200.0) & (coords[:, 1] > 0.0) & (coords[:, 1] > coords[:, 0])]
    assert len(smooth.exterior.coords) <= 6
    assert len(slope) >= 2
    assert np.allclose(slope[:, 1] - slope[:, 0], 0.5 * _PIXEL)
    assert _distance(stair.exterior, smooth.exterior) <= _PIXEL


def test_a_rectangle_is_left_as_it_is() -> None:
    bent = Polygon(
        [_xy(0, 0), _xy(600, 0), _xy(600, 300), _xy(300, 300), _xy(300, 700), _xy(0, 700)]
    )

    assert smooth_polygon(_DOMAIN, _PIXEL) is _DOMAIN
    assert smooth_polygon(bent, _PIXEL) is bent


def test_a_corner_between_two_long_edges_stays_a_corner() -> None:
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


def test_the_planner_smooths_the_catchment_a_face_family_follows() -> None:
    stair = _staircase()

    request = plan_mesh_request(_config(**_FACE), _inputs(stair))

    ring = request.family("watershed_boundary").lines[0]
    assert request.domain.equals(_DOMAIN)
    # The resampling cuts the corners of the smoothed outline at the local size.
    assert _distance(ring, stair.exterior) <= 1.25 * _PIXEL
    assert len(ring.coords) < len(stair.exterior.coords)
    assert Polygon(ring).is_valid
    assert abs(Polygon(ring).area - stair.area) / stair.area < 0.005
    notes = [note for note in request.notes if "outline was smoothed" in note]
    assert len(notes) == 1
    assert notes[0].startswith("geometry cleanup: the catchment outline was smoothed")
    assert f"{len(stair.exterior.coords)} vertices became" in notes[0]
    assert "its area moved by" in notes[0]
    assert "no point of it by more than" in notes[0]


def test_a_domain_that_is_the_catchment_follows_the_smoothed_outline() -> None:
    stair = _staircase()

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, domain=stair))

    ring = request.family("watershed_boundary").lines[0]
    assert request.domain is not stair
    assert request.domain.is_valid
    assert len(request.domain.exterior.coords) < 0.5 * len(stair.exterior.coords)
    assert _distance(request.domain.exterior, stair.exterior) <= _PIXEL
    assert abs(request.domain.area - stair.area) / stair.area < 0.005
    on_domain = shapely.distance(
        request.domain.exterior, shapely.points(shapely.get_coordinates(ring))
    )
    assert on_domain.max() < 1.0e-6
    assert any("the catchment and domain outline was smoothed" in n for n in request.notes)


def test_a_domain_that_is_a_buffer_of_the_catchment_is_smoothed_on_its_own() -> None:
    stair = _staircase(radius=200.0)
    buffered = stair.buffer(60.0, join_style="mitre")

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, domain=buffered))

    assert len(request.domain.exterior.coords) < 0.5 * len(buffered.exterior.coords)
    assert _distance(request.domain.exterior, buffered.exterior) <= _PIXEL
    assert request.domain.contains(Polygon(request.family("watershed_boundary").lines[0]))
    kinds = [note.split(" outline")[0] for note in request.notes if "outline was smoothed" in note]
    assert kinds == ["geometry cleanup: the catchment", "geometry cleanup: the domain"]


_CENTRE = np.array(_xy(480.0, 520.0))


def _pulled_off_corner(stair: Polygon, index: int) -> tuple[float, float]:
    """A vertex of the staircase that the smoothing alone would leave more than a quarter pixel off."""
    smooth = smooth_polygon(stair, _PIXEL)
    coords = np.asarray(stair.exterior.coords)
    gap = shapely.distance(smooth.exterior, shapely.points(coords))
    candidates = np.flatnonzero(gap > 0.25 * _PIXEL)
    return tuple(coords[candidates[index % len(candidates)]])


def _inward(point: tuple[float, float], length: float) -> np.ndarray:
    """The point *length* metres from *point* toward the middle of the catchment."""
    toward = _CENTRE - np.array(point)
    return np.array(point) + length * toward / np.hypot(*toward)


def _on_outline(request, point: tuple[float, float]) -> float:
    """Distance from *point* to the catchment ring the request follows."""
    return float(
        shapely.union_all(request.family("watershed_boundary").lines).distance(Point(point))
    )


@pytest.mark.parametrize("domain_is_catchment", [False, True])
def test_the_outlet_stays_on_the_outline(domain_is_catchment: bool) -> None:
    """The main river ends on the staircase, at its outlet: the smoothed outline passes there."""
    stair = _staircase()
    outlet = _pulled_off_corner(stair, 7)
    river = LineString([tuple(_inward(outlet, 200.0)), outlet])
    domain = stair if domain_is_catchment else _DOMAIN

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, domain=domain, rivers=(river,)))

    end = request.family("rivers").lines[0].coords[-1]
    assert Point(end).distance(Point(outlet)) < 1.0e-6
    assert _on_outline(request, end) < 1.0e-6


def test_a_river_ending_in_the_middle_of_a_step_stays_on_the_outline() -> None:
    stair = _staircase()
    coords = np.asarray(stair.exterior.coords)
    middles = 0.5 * (coords[:-1] + coords[1:])
    smooth = smooth_polygon(stair, _PIXEL)
    off = np.flatnonzero(shapely.distance(smooth.exterior, shapely.points(middles)) > 0.25 * _PIXEL)
    end = tuple(middles[off[len(off) // 3]])
    river = LineString([tuple(_inward(end, 150.0)), end])

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, rivers=(river,)))

    kept = request.family("rivers").lines[0].coords[-1]
    assert Point(kept).distance(Point(end)) < 1.0e-6
    assert _on_outline(request, kept) < 1.0e-6


def test_a_barrier_ending_on_the_outline_still_ends_on_it() -> None:
    stair = _staircase()
    start = _pulled_off_corner(stair, 11)
    wall = LineString([start, tuple(_inward(start, 120.0))])

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, barriers=(wall,)))

    kept = request.family("barriers").lines[0].coords[0]
    assert Point(kept).distance(Point(start)) < 1.0e-6
    assert _on_outline(request, kept) < 1.0e-6


def test_a_lake_touching_the_outline_still_touches_it() -> None:
    stair = _staircase()
    tip = _pulled_off_corner(stair, 2)
    middle = _inward(tip, 80.0)
    side = np.array([-(_CENTRE - np.array(tip))[1], (_CENTRE - np.array(tip))[0]])
    side = 25.0 * side / np.hypot(*side)
    lake = Polygon([tip, tuple(middle + side), tuple(middle - side)])
    assert lake.is_valid
    assert lake.distance(stair.exterior) < 1.0e-9

    request = plan_mesh_request(_config(**_FACE), _inputs(stair, lakes=(lake,)))

    assert _on_outline(request, tip) < 1.0e-6
    assert shapely.union_all(request.family("lakes").lines).distance(Point(tip)) < 1.0e-6


def test_a_regular_mesh_keeps_the_staircase() -> None:
    stair = _staircase()

    request = plan_mesh_request(_config("regular", **_FACE), _inputs(stair, domain=stair))

    ring = request.family("watershed_boundary").lines[0]
    assert len(ring.coords) == len(stair.exterior.coords)
    assert request.domain is stair
    assert not any("smoothed" in note for note in request.notes)


def test_a_catchment_the_mesh_does_not_follow_is_not_smoothed() -> None:
    stair = _staircase()

    request = plan_mesh_request(_config("voronoi"), _inputs(stair))

    assert request.domain.equals(_DOMAIN)
    assert request.family("watershed_boundary") is None
    assert not any("smoothed" in note for note in request.notes)


def test_the_smoothing_is_counted_in_the_journal(caplog: pytest.LogCaptureFixture) -> None:
    stair = _staircase()

    with caplog.at_level(logging.INFO):
        plan_mesh_request(_config(**_FACE), _inputs(stair))

    messages = [record.message for record in caplog.records]
    assert any(m.startswith("Smoothed the catchment outline: ") for m in messages)


def test_a_smoothing_that_leaves_the_polygon_invalid_keeps_the_staircase(
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
    assert any(
        "the catchment and domain outline stayed a staircase" in note for note in request.notes
    )
