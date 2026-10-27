"""The mesh step gathers what the planner reads besides ``[mesh]`` from the run context.

The lake table adds the hydraulic structures to refine: each cutoff wall, the
sill between two lakes, buffered from simplified outlines, and the disk under
the dam unless a wall zone already covers it. The barrier lines are each lake
wall, then each flow barrier. The bed regularisation writes the surface the
model top is sampled from after the mesh inputs are built, so toggling it
keeps the cached mesh.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely import normalize
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.cache import cache_key
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.planning import plan_mesh_request
from hydromodpy.spatial.mesh.refinement.lake_refinement import LakeRefinementConfig
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.workflow.steps.mesh_inputs import (
    _criterion_inputs,
    _domain_polygon,
    _river_trace,
    _sill_zone,
    barrier_lines,
    hydraulic_feature_geometries,
    lake_structures,
    planning_inputs,
)
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec

_LAKE = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 600.0), (0.0, 600.0)])
_OUTLET = (331315.0, 6781273.0)
_WALL_NEAR_THE_OUTLET = LineString([(331215.0, 6781273.0), (331255.0, 6781173.0)])
"""A wall 100 m from the outlet: its zone (260 m) and the disk (130 m) overlap by far."""
_WALL_FAR_FROM_THE_OUTLET = LineString([(329300.0, 6781273.0), (329400.0, 6781273.0)])
"""A wall on another lake 2 km away: the disk under the dam must stay."""


def _setup(wall: LineString, **lake_table: object):
    """The setup, geographic config and lake table of one reservoir with its cutoff wall."""
    table = LakeRefinementConfig(
        cell_size=80.0, buffer=160.0, dam_cell_size=60.0, dam_buffer=130.0, **lake_table
    )
    lakes = {"reservoir": {"polygon": _LAKE, "cutoff_wall_line": wall}}
    geographic = SimpleNamespace(x_outlet=_OUTLET[0], y_outlet=_OUTLET[1])
    setup = SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))
    return setup, geographic, table


def _labels(setup, geographic, table) -> set[str]:
    return {label for label, *_ in lake_structures(setup, geographic, table)}


def test_the_dam_disk_goes_when_the_wall_zone_reaches_the_outlet() -> None:
    labels = _labels(*_setup(_WALL_NEAR_THE_OUTLET))

    assert "dam_outlet" not in labels
    assert "voile:reservoir" in labels


def test_the_dam_disk_stays_when_the_wall_is_far_from_the_outlet() -> None:
    assert "dam_outlet" in _labels(*_setup(_WALL_FAR_FROM_THE_OUTLET))


def test_the_dam_disk_can_be_forced_next_to_a_wall() -> None:
    labels = _labels(*_setup(_WALL_NEAR_THE_OUTLET, dam_outlet_disk=True))

    assert {"dam_outlet", "voile:reservoir"} <= labels


def test_the_dam_disk_is_a_point_the_planner_dilates_by_the_dam_buffer() -> None:
    setup, geographic, table = _setup(_WALL_FAR_FROM_THE_OUTLET)

    structures = {s[0]: s for s in lake_structures(setup, geographic, table)}

    _, geometry, size, buffer = structures["dam_outlet"]
    assert (geometry.x, geometry.y) == _OUTLET
    assert (size, buffer) == (table.dam_cell_size, table.dam_buffer)


def test_no_dam_disk_without_a_declared_outlet() -> None:
    setup, _, table = _setup(_WALL_FAR_FROM_THE_OUTLET)

    assert _labels(setup, SimpleNamespace(), table) == {"voile:reservoir"}


def _two_lakes(gap: float) -> SimpleNamespace:
    """Two square lakes *gap* metres apart, and an entry of the lake table that is no lake."""
    lakes = {
        "a": {"polygon": box(0.0, 0.0, 400.0, 400.0)},
        "b": {"polygon": box(400.0 + gap, 0.0, 800.0 + gap, 400.0)},
        "note": "not a lake",
    }
    return SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))


def test_two_lakes_apart_get_a_sill_zone_finer_than_their_gap() -> None:
    """A cell wider than the gap would straddle both lakes, and MF6 LAK takes one lake per cell."""
    gap = 40.0
    table = LakeRefinementConfig(dam_cell_size=60.0)

    structures = {s[0]: s for s in hydraulic_feature_geometries(_two_lakes(gap), table)}

    _, zone, size, margin = structures["sill:a-b"]
    assert size < gap
    assert margin >= table.dam_cell_size
    assert zone.contains(box(400.0, 50.0, 400.0 + gap, 350.0))


def test_touching_lakes_get_no_sill_zone() -> None:
    structures = hydraulic_feature_geometries(_two_lakes(0.0), LakeRefinementConfig())

    assert not [label for label, *_ in structures if label.startswith("sill:")]


def test_no_structure_without_the_lake_table() -> None:
    setup, geographic, _ = _setup(LineString([(0, 0), (1, 1)]))

    assert lake_structures(setup, geographic, None) == ()


def test_the_barrier_lines_are_each_lake_wall_then_each_flow_barrier() -> None:
    wall = LineString([(1000.0, 100.0), (1000.0, 500.0)])
    fence = LineString([(200.0, 700.0), (800.0, 900.0)])
    flow = SimpleNamespace(
        sinks_sources={
            "lakes": {
                "a": {"polygon": _LAKE, "cutoff_wall_line": wall},
                "b": {"polygon": _LAKE},
            },
            "flow_barriers": {"f": {"barrier": object(), "line": fence}},
        }
    )

    assert barrier_lines(SimpleNamespace(flow=flow)) == (wall, fence)
    assert barrier_lines(SimpleNamespace(flow=SimpleNamespace(sinks_sources={}))) == ()


def _wiggly_lake(cx: float, n: int = 17000) -> Polygon:
    """A lake outline with *n* vertices and metre-scale noise, like a DEM-traced reservoir."""
    rng = np.random.default_rng(0)
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    r = 400.0 + 30.0 * np.sin(7.0 * t) + rng.uniform(-0.5, 0.5, n)
    return Polygon(np.column_stack([cx + r * np.cos(t), r * np.sin(t)]))


def test_the_sill_zone_of_simplified_outlines_matches_the_raw_buffer() -> None:
    """The outlines of two DEM-traced lakes are simplified first, C-07."""
    first, second = _wiggly_lake(0.0), _wiggly_lake(900.0)
    gap = first.distance(second)
    margin = max(1.5 * gap, 60.0)
    raw = first.buffer(margin).intersection(second.buffer(margin))
    sill_size = max(5.0, 0.4 * gap)

    zone = _sill_zone(first, second, margin, sill_size=sill_size)

    # The outline moves by at most the tolerance, a tenth of the sill size, twice.
    assert zone.hausdorff_distance(raw) <= 0.2 * sill_size


_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


def _geographic(**bed) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", river_network=_RIVER, bed_regularization=bed
    )


def _ctx(geographic: GeographicConfig, *, cells: int = 10) -> SimpleNamespace:
    """The slice of a run context the planner reads, over a square DEM of ``cells`` pixels."""
    support = RasterSupport(
        crs="EPSG:2154",
        dx=10.0,
        dy=10.0,
        xmin=0.0,
        xmax=10.0 * cells,
        ymin=0.0,
        ymax=10.0 * cells,
        nrows=cells,
        ncols=cells,
        nodata=-9999.0,
    )
    surface = Surface.from_geographic_dem(np.zeros((cells, cells)), support=support)
    return SimpleNamespace(
        cfg=SimpleNamespace(geographic=geographic, flow=SimpleNamespace(active_bc=[])),
        config_path=Path("project.toml"),
        setup=SimpleNamespace(
            domain=SimpleNamespace(surface_topo=surface),
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            domain_geographic=None,
            geographic_features=None,
            flow=None,
            workspace=None,
        ),
    )


def _key(ctx: SimpleNamespace) -> str:
    mesh_cfg = MeshConfig(engine="triangle", families={"rivers": "none", "geology": "none"})
    request = plan_mesh_request(mesh_cfg, planning_inputs(ctx, mesh_cfg))
    return cache_key(request, TriangleMeshEngine)


def test_the_bed_regularisation_keeps_the_cached_mesh() -> None:
    off = _ctx(_geographic(enabled=False))
    on = _ctx(_geographic(enabled=True, min_slope=5.0e-4))

    assert _key(on) == _key(off)


def test_another_dem_still_moves_the_key() -> None:
    assert _key(_ctx(_geographic(enabled=False))) != _key(
        _ctx(_geographic(enabled=False), cells=12)
    )


_CATCHMENT = box(100.0, 100.0, 900.0, 900.0)
_GRID = grid_spec(10, 10, 100.0, crs_wkt=LAMBERT93_WKT)


def _catchment_files(tmp_path: Path, *polygons, name: str = "watershed.shp") -> SimpleNamespace:
    """A setup whose delineation wrote *polygons* to *name* beside ``watershed.shp``."""
    gpd.GeoDataFrame(geometry=list(polygons), crs="EPSG:2154").to_file(tmp_path / name)
    return SimpleNamespace(
        domain_geographic=SimpleNamespace(watershed_shp=tmp_path / "watershed.shp")
    )


def _domain(setup: SimpleNamespace, extent: str, *, synthetic: bool = False) -> Polygon:
    geographic = SimpleNamespace(domain_extent=extent)
    return _domain_polygon(setup, geographic, _GRID, LAMBERT93_WKT, synthetic)


@pytest.mark.parametrize(
    ("extent", "name", "expected"),
    [
        ("watershed", "watershed.shp", _CATCHMENT),
        ("watershed_buff", "watershed_buff.shp", _CATCHMENT.buffer(50.0)),
    ],
)
def test_the_domain_is_the_catchment_or_its_buffer_as_the_delineation_wrote_it(
    tmp_path: Path, extent: str, name: str, expected: Polygon
) -> None:
    setup = _catchment_files(tmp_path, expected, name=name)

    assert normalize(_domain(setup, extent)).equals_exact(normalize(expected), 1.0e-6)


@pytest.mark.parametrize(("extent", "synthetic"), [("box", False), ("watershed", True)])
def test_the_domain_is_the_dem_box_for_a_box_extent_or_a_synthetic_support(
    extent: str, synthetic: bool
) -> None:
    assert _domain(SimpleNamespace(), extent, synthetic=synthetic).equals(box(0, 0, 1000, 1000))


def test_the_domain_of_a_catchment_in_two_parts_is_the_larger(tmp_path: Path) -> None:
    island = box(950.0, 950.0, 990.0, 990.0)
    setup = _catchment_files(tmp_path, _CATCHMENT, island)

    assert normalize(_domain(setup, "watershed")).equals_exact(normalize(_CATCHMENT), 1.0e-6)


def test_a_catchment_domain_without_its_file_is_refused(tmp_path: Path) -> None:
    setup = SimpleNamespace(
        domain_geographic=SimpleNamespace(watershed_shp=tmp_path / "watershed.shp")
    )

    with pytest.raises(MeshError, match="watershed_buff.shp, not found"):
        _domain(setup, "watershed_buff")


def test_a_catchment_file_with_no_polygon_is_refused(tmp_path: Path) -> None:
    setup = _catchment_files(tmp_path, None)

    with pytest.raises(MeshError, match="holds no polygon"):
        _domain(setup, "watershed")


def test_a_mesh_that_follows_the_rivers_without_a_traced_network_is_refused() -> None:
    setup = SimpleNamespace(geographic_features=None)

    with pytest.raises(MeshError, match="no river network was traced from the DEM"):
        _river_trace(setup, MeshConfig(engine="triangle"), active_bc=set(), synthetic=False)


_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}


def _top(cells: int = 10, *, nodata_at: tuple[int, int] | None = None) -> SimpleNamespace:
    """A setup whose model top is a flat DEM of ``cells`` pixels, one of them maybe without data."""
    support = RasterSupport(
        crs="EPSG:2154",
        dx=100.0,
        dy=100.0,
        xmin=0.0,
        xmax=100.0 * cells,
        ymin=0.0,
        ymax=100.0 * cells,
        nrows=cells,
        ncols=cells,
        nodata=-9999.0,
    )
    elevation = np.zeros((cells, cells))
    if nodata_at is not None:
        elevation[nodata_at] = -9999.0
    surface = Surface.from_geographic_dem(elevation, support=support)
    return SimpleNamespace(domain=SimpleNamespace(surface_topo=surface), workspace=None)


def _criteria_config(*zones: dict) -> MeshConfig:
    return MeshConfig(engine="voronoi", cell_size=200.0, refinement_zone=list(zones))


def test_a_zone_on_the_height_above_the_stream_reads_the_dem_and_the_traced_network() -> None:
    trace = RiverMeshTrace(
        source_kind="geographic_generated",
        crs_wkt=LAMBERT93_WKT,
        lines=(LineString([(550.0, 0.0), (550.0, 1000.0)]),),
    )

    criteria = _criterion_inputs(_top(nodata_at=(2, 3)), _criteria_config(_HAND), _GRID, trace)

    assert criteria.stream_lines == trace.lines
    assert np.isnan(criteria.elevation[2, 3])
    assert np.count_nonzero(np.isnan(criteria.elevation)) == 1
    assert criteria.run_fields == {}


def test_a_model_top_of_another_shape_than_the_mesh_grid_is_refused() -> None:
    with pytest.raises(MeshError, match=r"the model top holds \(12, 12\) values"):
        _criterion_inputs(_top(12), _criteria_config(_HAND), _GRID, None)


def test_a_zone_that_reads_an_earlier_run_needs_a_workspace() -> None:
    zone = {"where": "watertable_depth", "below": 1.0, "run": "coarse", "cell_size": 20.0}

    with pytest.raises(MeshError, match="no workspace is set up"):
        _criterion_inputs(_top(), _criteria_config(zone), _GRID, None)
