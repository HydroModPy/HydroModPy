"""The planner adds the barrier family and welds its shore stretch to the lake ring."""

from __future__ import annotations

import numpy as np
import shapely
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.physics.flow.cutoff_wall_shore import SnappedWall, snap_wall_to_shore
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import (
    BARRIER_FAMILY,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from tests._helpers.reservoir_dam import DOMAIN, reservoir, trace

WKT = CRS.from_epsg(2154).to_wkt()
GRADED = {"engine": "voronoi", "cell_size": 60.0, "lake_refinement": {"cell_size": 30.0}}


def _grid() -> RasterGridSpec:
    xmin, ymin, xmax, ymax = DOMAIN.bounds
    return RasterGridSpec(
        xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, dx=10.0, dy=10.0, nrow=80, ncol=120, crs_wkt=WKT
    )


def _inputs(barriers: tuple[LineString, ...], *, lakes: tuple = ()) -> PlanningInputs:
    return PlanningInputs(
        dem_grid=_grid(),
        crs_wkt=WKT,
        domain=DOMAIN,
        river_trace=None,
        watershed=DOMAIN,
        lakes=lakes,
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
        barriers=barriers,
    )


def _walled(offset: float, mesh: dict) -> tuple[SnappedWall, MeshRequest]:
    wall = snap_wall_to_shore(reservoir(), trace(offset), 50.0)
    request = plan_mesh_request(
        MeshConfig.model_validate(mesh), _inputs((wall.line,), lakes=(wall.polygon,))
    )
    return wall, request


def test_a_wall_on_the_shore_takes_the_ring_vertices_bit_for_bit() -> None:
    for offset in (12.0, -30.0):
        wall, request = _walled(offset, GRADED)
        ring = {tuple(xy) for xy in shapely.get_coordinates(request.family("lakes").lines[0])}
        coords = shapely.get_coordinates(request.family(BARRIER_FAMILY).lines[0])
        on_ring = np.array([tuple(xy) in ring for xy in coords])
        stretch = np.flatnonzero(on_ring)

        assert stretch.size >= 3
        assert np.all(np.diff(stretch) == 1)
        on_shore = shapely.distance(shapely.points(coords[stretch]), wall.shore)
        assert on_shore.max() < 1.0e-6


def test_the_wall_keeps_its_corners_and_its_ends() -> None:
    wall, request = _walled(12.0, GRADED)
    line = request.family(BARRIER_FAMILY).lines[0]
    corners = shapely.get_coordinates(wall.line)[[0, 1, 2, -3, -2, -1]]

    assert np.all(shapely.distance(shapely.points(corners), line) < 1.0e-6)
    assert shapely.hausdorff_distance(line, wall.line) < 1.0e-6


def test_the_switch_set_to_none_leaves_the_barriers_out() -> None:
    _, request = _walled(12.0, {**GRADED, "families": {"barriers": "none"}})

    assert request.family(BARRIER_FAMILY) is None
    assert request.family("lakes") is not None


def test_a_staircase_engine_gets_the_raw_barrier_line() -> None:
    wall, request = _walled(12.0, {"engine": "regular", "cell_size": 40.0})

    assert request.family(BARRIER_FAMILY).lines == (wall.line,)


def test_a_barrier_without_lake_is_resampled_on_its_own() -> None:
    line = LineString([(350_100.0, 6_780_100.0), (350_700.0, 6_780_700.0)])
    request = plan_mesh_request(MeshConfig.model_validate(GRADED), _inputs((line,)))
    resampled = request.family(BARRIER_FAMILY).lines[0]

    assert len(resampled.coords) > 2
    assert shapely.hausdorff_distance(resampled, line) < 1.0e-6


def test_a_barrier_corner_stays_a_vertex_where_another_line_is_resampled() -> None:
    grid = RasterGridSpec(
        xmin=0.0, xmax=100.0, ymin=0.0, ymax=100.0, dx=1.0, dy=1.0, nrow=100, ncol=100, crs_wkt=WKT
    )
    field = SizeField(np.full((100, 100), 20.0), grid)
    bent = LineString([(10.0, 10.0), (50.0, 12.0), (52.0, 90.0)])
    families = (
        LineFamilySpec(BARRIER_FAMILY, "face", (bent,)),
        LineFamilySpec("geology", "face", (LineString(np.asarray(bent.coords) + [5.0, 0.0]),)),
    )
    barrier, contact = resample_families(
        families, domain=box(0, 0, 100, 100), size_field=field
    ).families

    assert (50.0, 12.0) in set(barrier.lines[0].coords)
    assert (55.0, 12.0) not in set(contact.lines[0].coords)


def test_a_fixed_point_on_a_line_stays_a_vertex() -> None:
    grid = RasterGridSpec(
        xmin=0.0, xmax=100.0, ymin=0.0, ymax=100.0, dx=1.0, dy=1.0, nrow=100, ncol=100, crs_wkt=WKT
    )
    field = SizeField(np.full((100, 100), 30.0), grid)
    family = LineFamilySpec("geology", "face", (LineString([(5.0, 50.0), (95.0, 50.0)]),))
    (resampled,) = resample_families(
        (family,),
        domain=box(0, 0, 100, 100),
        size_field=field,
        fixed_points=np.array([[41.0, 50.0]]),
    ).families

    assert (41.0, 50.0) in set(resampled.lines[0].coords)
