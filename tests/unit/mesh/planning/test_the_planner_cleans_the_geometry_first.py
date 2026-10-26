"""The planner cleans the geometry of its inputs before it sizes them.

Close vertices merge, a line end that misses another line by less than a
tenth of the DEM pixel is snapped onto it, and cut back first when it ran
along it. A hole of one square metre in a lake goes, so a generated Voronoi
mesh of the Cheze lakes builds. A clean input passes unchanged.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig, MeshFamiliesConfig
from hydromodpy.spatial.mesh.planning.cleanup import (
    CLEANUP_PIXEL_SHARE,
    GeometryCleanup,
    clean_lines,
)
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, RasterGridSpec

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 330_000.0, 6_780_000.0
_PIXEL = 10.0
_TOL = CLEANUP_PIXEL_SHARE * _PIXEL
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
_FAMILIES = MeshFamiliesConfig()


def _xy(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


def _inputs(*, rivers=(), barriers=(), lakes=()) -> PlanningInputs:
    trace = (
        RiverMeshTrace(source_kind="file", crs_wkt=_WKT, lines=tuple(rivers)) if rivers else None
    )
    return PlanningInputs(
        dem_grid=_GRID,
        crs_wkt=_WKT,
        domain=_DOMAIN,
        river_trace=trace,
        watershed=None,
        lakes=tuple(lakes),
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=True,
        barriers=tuple(barriers),
    )


def _cleaned(inputs: PlanningInputs) -> tuple[PlanningInputs, GeometryCleanup]:
    cleanup = GeometryCleanup(tolerance=_TOL)
    return clean_lines(inputs, _FAMILIES, cleanup), cleanup


def test_a_clean_input_passes_unchanged() -> None:
    main = LineString([_xy(0.0, 500.0), _xy(500.0, 500.0), _xy(1000.0, 520.0)])
    tributary = LineString([_xy(300.0, 100.0), _xy(500.0, 500.0)])
    wall = LineString([_xy(600.0, 200.0), _xy(800.0, 200.0)])
    inputs = _inputs(
        rivers=(main, tributary), barriers=(wall,), lakes=(box(*_xy(100, 700), *_xy(300, 900)),)
    )

    cleaned, cleanup = _cleaned(inputs)

    assert cleaned is inputs
    assert cleanup.notes() == ()


def test_vertices_closer_than_the_tolerance_merge_and_the_ends_stay() -> None:
    wall = LineString(
        [
            _xy(600.0, 200.0),
            _xy(700.0, 200.0),
            _xy(700.3, 200.2),
            _xy(799.8, 200.0),
            _xy(800.0, 200.0),
        ]
    )

    cleaned, cleanup = _cleaned(_inputs(barriers=(wall,)))

    coords = np.asarray(cleaned.barriers[0].coords)
    assert cleanup.merged_vertices == 2
    assert coords.tolist() == [
        list(_xy(600.0, 200.0)),
        list(_xy(700.0, 200.0)),
        list(_xy(800.0, 200.0)),
    ]


def test_a_river_end_short_of_the_boundary_is_snapped_onto_it() -> None:
    river = LineString([_xy(200.0, 400.0), _xy(600.0, 500.0), _xy(999.4, 550.0)])
    mesh_cfg = MeshConfig(engine="regular", cell_size=50.0)

    request = plan_mesh_request(mesh_cfg, _inputs(rivers=(river,)))

    end = Point(request.family("rivers").lines[0].coords[-1])
    assert end.distance(_DOMAIN.exterior) == pytest.approx(0.0, abs=1e-9)
    assert any("1 line ends within 1 m of another line were snapped" in n for n in request.notes)


def test_a_river_end_running_along_a_wall_is_cut_back_then_snapped() -> None:
    wall = LineString([_xy(200.0, 300.0), _xy(800.0, 300.0)])
    river = LineString([_xy(500.0, 600.0), _xy(500.0, 300.5), _xy(700.0, 300.5)])

    cleaned, cleanup = _cleaned(_inputs(rivers=(river,), barriers=(wall,)))

    kept = cleaned.river_trace.lines[0]
    assert (cleanup.cut_ends, cleanup.snapped_ends) == (1, 1)
    assert kept.length == pytest.approx(300.0, abs=1e-6)
    assert Point(kept.coords[-1]).distance(wall) == pytest.approx(0.0, abs=1e-9)
    assert shapely.intersection(kept, wall.buffer(0.9 * _TOL)).length <= _TOL


def test_a_wall_running_along_another_line_keeps_its_length() -> None:
    river = LineString([_xy(200.0, 300.0), _xy(800.0, 300.0)])
    wall = LineString([_xy(500.0, 600.0), _xy(500.0, 300.5), _xy(700.0, 300.5)])

    cleaned, cleanup = _cleaned(_inputs(rivers=(river,), barriers=(wall,)))

    kept = cleaned.barriers[0]
    assert (cleanup.cut_ends, cleanup.snapped_ends) == (0, 1)
    assert kept.coords[-1] == _xy(700.0, 300.0)
    assert kept.length == pytest.approx(wall.length, abs=1e-2)


def test_a_wall_laid_on_a_shore_keeps_the_shore_vertices() -> None:
    lake = Polygon([_xy(100.0, 700.0), _xy(300.0, 700.0), _xy(300.4, 700.0), _xy(300.0, 900.0)])
    wall = LineString([_xy(200.0, 700.0), _xy(300.0, 700.0), _xy(300.4, 700.0), _xy(300.2, 800.0)])

    cleaned, cleanup = _cleaned(_inputs(barriers=(wall,), lakes=(lake,)))

    assert cleanup.merged_vertices == 0
    assert cleaned.lakes[0] is lake
    assert cleaned.barriers[0] is wall


def test_two_ends_that_miss_each_other_meet_once() -> None:
    first = LineString([_xy(200.0, 300.0), _xy(500.0, 300.0)])
    second = LineString([_xy(500.6, 300.0), _xy(800.0, 300.0)])

    cleaned, cleanup = _cleaned(_inputs(barriers=(first, second)))

    assert cleanup.snapped_ends == 1
    assert cleaned.barriers[0].coords[-1] == cleaned.barriers[1].coords[0]


def test_each_kind_of_change_is_counted_in_the_journal(caplog: pytest.LogCaptureFixture) -> None:
    wall = LineString([_xy(200.0, 300.0), _xy(200.2, 300.0), _xy(800.0, 300.0)])
    loose = LineString([_xy(500.0, 600.0), _xy(500.0, 300.6)])
    mesh_cfg = MeshConfig(engine="regular", cell_size=50.0)

    with caplog.at_level(logging.INFO):
        request = plan_mesh_request(mesh_cfg, _inputs(barriers=(wall, loose)))

    messages = [record.message for record in caplog.records]
    assert "Merged 1 line vertices closer than 1 m." in messages
    assert "Snapped 1 line ends within 1 m of another line." in messages
    assert len(request.family(BARRIER_FAMILY).lines) == 2


def _holed(outer: Polygon, centres: list[tuple[float, float]]) -> Polygon:
    holes = [box(x - 0.5, y - 0.5, x + 0.5, y + 0.5).exterior.coords for x, y in centres]
    return Polygon(outer.exterior.coords, holes)


def test_a_lake_with_holes_of_one_square_metre_meshes_in_voronoi() -> None:
    """The Cheze case: nine 1 m2 holes of a polygonised bathymetry in two lakes."""
    upper = _holed(
        Point(*_xy(300.0, 650.0)).buffer(180.0),
        [_xy(250.0 + 20.0 * k, 650.0 + (-1) ** k * 15.0) for k in range(5)],
    )
    lower = _holed(
        Point(*_xy(700.0, 300.0)).buffer(150.0),
        [_xy(680.0 + 20.0 * k, 300.0) for k in range(4)],
    )
    mesh_cfg = MeshConfig(
        engine="voronoi", cell_size=80.0, river_cell_size=40.0, lake_refinement={"cell_size": 40.0}
    )
    river = LineString([_xy(0.0, 980.0), _xy(300.0, 900.0), _xy(1000.0, 20.0)])

    request = plan_mesh_request(mesh_cfg, _inputs(rivers=(river,), lakes=(upper, lower)))
    mesh = registry.create("voronoi").build(request)

    assert len(request.family("lakes").lines) == 2
    assert any("9 holes of the domain, the lakes and the catchment" in n for n in request.notes)
    assert mesh.n_cells > 0
    assert mesh.chains("rivers")


def test_the_ends_of_a_family_the_mesh_ignores_stay_where_they_are() -> None:
    river = LineString([_xy(200.0, 400.0), _xy(999.4, 550.0)])
    families = MeshFamiliesConfig(rivers="none")
    cleanup = GeometryCleanup(tolerance=_TOL)
    inputs = _inputs(rivers=(river,))

    assert clean_lines(inputs, families, cleanup) is inputs
    assert cleanup.snapped_ends == 0
