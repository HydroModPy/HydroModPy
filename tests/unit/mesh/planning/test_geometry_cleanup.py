"""The planner cleans the geometry of its inputs before it sizes them.

Close vertices merge, a line end that misses another line by less than a
tenth of the DEM pixel is snapped onto it, and cut back first when it ran
along it. A hole smaller than one local cell squared goes, for every engine,
so a generated Voronoi mesh of the Cheze lakes builds. A clean input passes
unchanged, and a triangulation read keeps its holes.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
import shapely
from hypothesis import given, settings
from hypothesis import strategies as st
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from hydromodpy.catchment.algorithms.river_mesh_trace import RiverMeshTrace
from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.mesh.mesh_config import MeshConfig, MeshFamiliesConfig
from hydromodpy.mesh.planning import plan
from hydromodpy.mesh.planning.geology_contacts import GeologyLines
from hydromodpy.mesh.planning.geometry_cleanup import (
    CLEANUP_PIXEL_SHARE,
    GeometryCleanup,
    clean_lines,
)
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.mesh.request import InputTriangulation
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import L93_ORIGIN, grid_spec, planning_inputs, square_domain

pytestmark = pytest.mark.usefixtures("builtin_engines")

X0, Y0 = L93_ORIGIN
_PIXEL = 10.0
_TOL = CLEANUP_PIXEL_SHARE * _PIXEL
_DOMAIN = square_domain(1000.0, x0=X0, y0=Y0)
_GRID = grid_spec(100, 100, _PIXEL, xmin=X0, ymin=Y0)
_FAMILIES = MeshFamiliesConfig()

_PROPERTY = settings(derandomize=True, max_examples=50, deadline=None)


def _xy(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


def _inputs(*, rivers=(), barriers=(), lakes=(), **overrides: object) -> PlanningInputs:
    trace = (
        RiverMeshTrace(source_kind="file", crs_wkt=TEST_CRS_WKT, lines=tuple(rivers))
        if rivers
        else None
    )
    members = {
        "domain": _DOMAIN,
        "river_trace": trace,
        "lakes": tuple(lakes),
        "barriers": tuple(barriers),
        **overrides,
    }
    return planning_inputs(_GRID, **members)


def _cleaned(
    inputs: PlanningInputs, families: MeshFamiliesConfig = _FAMILIES
) -> tuple[PlanningInputs, GeometryCleanup]:
    cleanup = GeometryCleanup(tolerance=_TOL)
    return clean_lines(inputs, families, cleanup), cleanup


def _notes(**counts: int) -> set[str]:
    """The notes the cleanup writes for *counts*, at the tolerance of these tests."""
    notes = set(GeometryCleanup(tolerance=_TOL, **counts).notes())
    assert notes
    return notes


def test_one_note_per_kind() -> None:
    cleanup = GeometryCleanup(
        tolerance=_TOL, merged_vertices=1, cut_ends=1, snapped_ends=1, dropped_holes=2
    )

    assert len(set(cleanup.notes())) == 4


def _with_a_close_vertex(polygon: Polygon) -> Polygon:
    """*polygon* with a vertex put a third of the tolerance after its first one."""
    coords = list(polygon.exterior.coords)
    x, y = coords[0]
    (nx, ny) = coords[1]
    step = np.array([nx - x, ny - y]) / np.hypot(nx - x, ny - y)
    close = (x + step[0] * _TOL / 3.0, y + step[1] * _TOL / 3.0)
    return Polygon([coords[0], close, *coords[1:]])


def test_close_vertices_merge() -> None:
    domain = _with_a_close_vertex(_DOMAIN)
    lake = _with_a_close_vertex(box(*_xy(100, 700), *_xy(300, 900)))
    catchment = _with_a_close_vertex(box(*_xy(50, 50), *_xy(950, 950)))
    inputs = _inputs(lakes=(lake,), domain=domain, watershed=catchment, synthetic=False)

    cleaned, cleanup = _cleaned(inputs, MeshFamiliesConfig(watershed_boundary="face"))

    assert cleanup.merged_vertices == 3
    for before, after in ((domain, cleaned.domain), (lake, cleaned.lakes[0])):
        assert len(after.exterior.coords) == len(before.exterior.coords) - 1
        assert after.is_valid
    assert len(cleaned.watershed.exterior.coords) == len(catchment.exterior.coords) - 1


def test_invalid_merge_is_skipped() -> None:
    """A wall pins the tip of a spike: flattening it would put the hole beside it outside."""
    tip = _xy(40.4, 0.5)
    domain = Polygon(
        [_xy(0, 0), _xy(40.3, 0), tip, _xy(40.5, 0), _xy(1000, 0), _xy(1000, 1000), _xy(0, 1000)],
        [[_xy(20, 0.2), _xy(30, 5), _xy(10, 5)]],
    )
    assert domain.is_valid
    wall = LineString([tip, _xy(40.4, 50.0)])

    cleaned, cleanup = _cleaned(_inputs(barriers=(wall,), domain=domain))

    assert cleaned.domain is domain
    assert cleanup.merged_vertices == 0


def test_two_part_lake_unchanged() -> None:
    lakes = MultiPolygon(
        [
            box(*_xy(100, 700), *_xy(200, 800)),
            _with_a_close_vertex(box(*_xy(300, 700), *_xy(400, 800))),
        ]
    )

    cleaned, cleanup = _cleaned(_inputs(lakes=(lakes,)))

    assert cleaned.lakes[0] is lakes
    assert cleanup.merged_vertices == 0


def test_river_end_snaps_to_boundary() -> None:
    river = LineString([_xy(200.0, 400.0), _xy(600.0, 500.0), _xy(999.4, 550.0)])
    mesh_cfg = MeshConfig(engine="regular", cell_size=50.0)

    request = plan_mesh_request(mesh_cfg, _inputs(rivers=(river,)))

    end = Point(request.family("rivers").lines[0].coords[-1])
    assert end.distance(_DOMAIN.exterior) == pytest.approx(0.0, abs=1e-9)
    assert _notes(snapped_ends=1) <= set(request.notes)


def test_contact_end_snaps_to_boundary() -> None:
    contact = LineString([_xy(500.0, 999.5), _xy(500.0, 0.0)])
    geology = GeologyLines(lines=(contact,), zone_left=("granite",), zone_right=("schist",))

    cleaned, cleanup = _cleaned(_inputs(geology=geology))

    assert cleanup.snapped_ends == 1
    assert cleaned.geology.lines[0].coords[0] == _xy(500.0, 1000.0)
    assert cleaned.geology.zone_left == geology.zone_left


@pytest.mark.parametrize("end", ["tail", "head"])
def test_river_along_wall_cut_back(end: str) -> None:
    wall = LineString([_xy(200.0, 300.0), _xy(800.0, 300.0)])
    river = LineString([_xy(500.0, 600.0), _xy(500.0, 300.5), _xy(700.0, 300.5)])
    if end == "head":
        river = river.reverse()

    cleaned, cleanup = _cleaned(_inputs(rivers=(river,), barriers=(wall,)))

    kept = cleaned.river_trace.lines[0]
    at_the_wall = kept.coords[-1] if end == "tail" else kept.coords[0]
    assert (cleanup.cut_ends, cleanup.snapped_ends) == (1, 1)
    assert kept.length == pytest.approx(300.0, abs=1e-6)
    assert Point(at_the_wall).distance(wall) == pytest.approx(0.0, abs=1e-9)
    assert shapely.intersection(kept, wall.buffer(0.9 * _TOL)).length <= _TOL


def test_wall_along_river_keeps_length() -> None:
    river = LineString([_xy(200.0, 300.0), _xy(800.0, 300.0)])
    wall = LineString([_xy(500.0, 600.0), _xy(500.0, 300.5), _xy(700.0, 300.5)])

    cleaned, cleanup = _cleaned(_inputs(rivers=(river,), barriers=(wall,)))

    kept = cleaned.barriers[0]
    assert (cleanup.cut_ends, cleanup.snapped_ends) == (0, 1)
    assert kept.coords[-1] == _xy(700.0, 300.0)
    assert kept.length == pytest.approx(wall.length, abs=1e-2)


def test_short_stub_stays_a_line() -> None:
    """Snapping its free end onto the vertex it already ends on would leave a point."""
    wall = LineString([_xy(200.0, 300.0), _xy(500.0, 300.0), _xy(800.0, 300.0)])
    stub = LineString([_xy(500.0, 300.5), _xy(500.0, 300.0)])

    cleaned, cleanup = _cleaned(_inputs(barriers=(wall, stub)))

    assert cleaned.barriers[1] is stub
    assert cleanup.snapped_ends == 0


def test_overshoot_is_cut() -> None:
    wall = LineString([_xy(200.0, 300.0), _xy(500.0, 300.0), _xy(800.0, 300.0)])
    fence = LineString([_xy(500.0, 299.5), _xy(500.0, 300.0), _xy(500.0, 600.0)])

    cleaned, cleanup = _cleaned(_inputs(barriers=(wall, fence)))

    assert cleanup.snapped_ends == 1
    assert list(cleaned.barriers[1].coords) == [_xy(500.0, 300.0), _xy(500.0, 600.0)]


def _holed(outer: Polygon, *holes: Polygon) -> Polygon:
    return Polygon(outer.exterior.coords, [hole.exterior.coords for hole in holes])


def test_cheze_lakes_mesh_in_voronoi() -> None:
    """The Cheze case: nine 1 m2 holes of a polygonized bathymetry in two lakes."""

    def square(x: float, y: float) -> Polygon:
        return box(x - 0.5, y - 0.5, x + 0.5, y + 0.5)

    upper = _holed(
        Point(*_xy(300.0, 650.0)).buffer(180.0),
        *(square(*_xy(250.0 + 20.0 * k, 650.0 + (-1) ** k * 15.0)) for k in range(5)),
    )
    lower = _holed(
        Point(*_xy(700.0, 300.0)).buffer(150.0),
        *(square(*_xy(680.0 + 20.0 * k, 300.0)) for k in range(4)),
    )
    mesh_cfg = MeshConfig(
        engine="voronoi", cell_size=80.0, river_cell_size=40.0, lake_refinement={"cell_size": 40.0}
    )
    river = LineString([_xy(0.0, 980.0), _xy(300.0, 900.0), _xy(1000.0, 20.0)])

    request = plan_mesh_request(mesh_cfg, _inputs(rivers=(river,), lakes=(upper, lower)))
    mesh = VoronoiMeshEngine().build(request)

    assert len(request.family("lakes").lines) == 2
    assert _notes(dropped_holes=9) <= set(request.notes)
    assert mesh.n_cells > 0
    assert mesh.chains("rivers")


_TINY = 0.5
"""Radius [m] of a hole of 0.8 m2, as the pixels of a polygonized bathymetry leave."""
_WIDE = 25.0
"""Radius [m] of a hole of 1960 m2, larger than one 40 m cell squared."""


def _with_holes(*, tiny: bool = True, **overrides: object) -> PlanningInputs:
    """A lake with a wide hole, a second lake, and a tiny hole in the domain, the lake and the catchment."""
    tiny_holes = (
        {
            "domain": (Point(*_xy(50.0, 50.0)).buffer(_TINY),),
            "lake": (Point(*_xy(280.0, 750.0)).buffer(_TINY),),
            "watershed": (Point(*_xy(200.0, 200.0)).buffer(_TINY),),
        }
        if tiny
        else {"domain": (), "lake": (), "watershed": ()}
    )
    lake = _holed(
        Point(*_xy(300.0, 750.0)).buffer(60.0),
        *tiny_holes["lake"],
        Point(*_xy(320.0, 750.0)).buffer(_WIDE),
    )
    return _inputs(
        lakes=(lake, Point(*_xy(750.0, 200.0)).buffer(40.0)),
        domain=_holed(_DOMAIN, *tiny_holes["domain"]),
        watershed=_holed(box(*_xy(100.0, 100.0), *_xy(900.0, 900.0)), *tiny_holes["watershed"]),
        synthetic=False,
        **overrides,
    )


@pytest.mark.parametrize(
    "mesh_cfg",
    [
        MeshConfig(engine="triangle", cell_size=40.0, families={"watershed_boundary": "face"}),
        MeshConfig(engine="regular", cell_size=40.0, families={"watershed_boundary": "face"}),
    ],
    ids=["graded", "regular"],
)
def test_small_holes_dropped(mesh_cfg: MeshConfig, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        request = plan_mesh_request(mesh_cfg, _with_holes())

    assert len(request.domain.interiors) == 0
    assert len(request.family("lakes").lines) == 3  # the lake, its wide hole, the second lake
    assert len(request.family("watershed_boundary").lines) == 1
    assert _notes(dropped_holes=3) <= set(request.notes)
    assert [r.message for r in caplog.records if "Dropped" in r.message] == [
        "Dropped 3 holes smaller than one local cell squared."
    ]


@pytest.fixture
def cleanups(monkeypatch: pytest.MonkeyPatch) -> list[GeometryCleanup]:
    """The cleanup records the planner makes, in order."""
    made: list[GeometryCleanup] = []

    class _Recorded(GeometryCleanup):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(plan, "GeometryCleanup", _Recorded)
    return made


def test_clean_input_unchanged(
    cleanups: list[GeometryCleanup],
) -> None:
    inputs = _with_holes(tiny=False)
    mesh_cfg = MeshConfig(
        engine="triangle",
        cell_size=80.0,
        river_cell_size=20.0,
        lake_refinement={"cell_size": 20.0},
        families={"watershed_boundary": "face"},
    )

    request = plan_mesh_request(mesh_cfg, inputs)

    (cleanup,) = cleanups
    assert request.domain.equals(inputs.domain)
    assert len(request.family("lakes").lines) == 3
    assert cleanup.dropped_holes == 0
    assert cleanup.notes() == ()


def test_triangulation_keeps_holes(cleanups: list[GeometryCleanup]) -> None:
    triangulation = InputTriangulation(
        vertices=np.array([_xy(0.0, 0.0), _xy(800.0, 0.0), _xy(800.0, 900.0), _xy(0.0, 900.0)]),
        triangles=np.array([[0, 1, 2], [0, 2, 3]]),
        edge_labels={},
    )
    cfg = MeshConfig(engine="voronoi", triangle={"path": "m.msh"})

    request = plan_mesh_request(cfg, _with_holes(input_triangulation=triangulation))

    (cleanup,) = cleanups
    assert len(request.family("lakes").lines) == 4
    assert cleanup.dropped_holes == 0


_COORD = st.floats(min_value=50.0, max_value=950.0, allow_nan=False)
_NUDGE = st.floats(min_value=-1.5 * _TOL, max_value=1.5 * _TOL, allow_nan=False)


@st.composite
def _lines_near_each_other(draw: st.DrawFn) -> list[LineString]:
    """Two to four polylines, each vertex either free or a nudge off a vertex drawn before it."""
    lines: list[LineString] = []
    vertices: list[tuple[float, float]] = []
    for _ in range(draw(st.integers(2, 4))):
        coords = []
        for _ in range(draw(st.integers(2, 5))):
            if vertices and draw(st.booleans()):
                x, y = draw(st.sampled_from(vertices))
                point = (x + draw(_NUDGE), y + draw(_NUDGE))
            else:
                point = (draw(_COORD), draw(_COORD))
            coords.append(_xy(*point))
            vertices.append(point)
        # A line whose ends sit within a few tolerances collapses when its vertices merge.
        if Point(coords[0]).distance(Point(coords[-1])) > 6.0 * _TOL:
            lines.append(LineString(coords))
    return lines


@_PROPERTY
@given(lines=_lines_near_each_other(), rivers=st.integers(0, 4))
def test_cleaned_line_stays_within_tolerance(lines: list[LineString], rivers: int) -> None:
    """Merging moves a line by less than the tolerance, snapping an end by at most one."""
    inputs = _inputs(rivers=lines[:rivers], barriers=lines[rivers:])

    cleaned, _ = _cleaned(inputs)

    after = [*(cleaned.river_trace.lines if cleaned.river_trace else ()), *cleaned.barriers]
    assert len(after) == len(lines)
    for before, line in zip(lines, after, strict=True):
        assert line.length > 0.0
        assert before.buffer(2.0 * _TOL + 1.0e-6).covers(line)


def test_merge_counted_once() -> None:
    """The counts are what changed, so a second cleanup of a clean result counts nothing."""
    wall = LineString([_xy(600.0, 200.0), _xy(700.0, 200.0), _xy(700.3, 200.2), _xy(800.0, 200.0)])
    once, first = _cleaned(_inputs(barriers=(wall,)))

    twice, second = _cleaned(once)

    assert first.merged_vertices == 1
    assert twice is once
    assert second.notes() == ()
