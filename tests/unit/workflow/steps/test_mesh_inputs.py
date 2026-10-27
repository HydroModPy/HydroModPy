"""The mesh step gathers what the planner reads besides ``[mesh]`` from the run context.

The lake table hands the cutoff walls, the lake footprints and the declared
outlet to the size rules of the lake structures. The barrier lines are each
lake wall, then each flow barrier. The bed regularisation writes the surface the
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
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.cache import cache_key
from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.planning.lake_structures import lake_structures
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.refinement_config import LakeRefinementConfig
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.workflow.steps.mesh_inputs import (
    _criterion_inputs,
    _domain_polygon,
    _river_trace,
    barrier_lines,
    planning_inputs,
)
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec

_LAKE = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 600.0), (0.0, 600.0)])


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


def test_the_lake_table_reaches_the_planner_as_walls_footprints_and_outlet() -> None:
    """An entry that is no lake is skipped, and a lake without a wall gives its footprint only."""
    wall = LineString([(0.0, 300.0), (0.0, 500.0)])
    first, second = box(0.0, 0.0, 400.0, 400.0), box(440.0, 0.0, 840.0, 400.0)
    lakes = {
        "a": {"polygon": first, "cutoff_wall_line": wall},
        "b": {"polygon": second, "cutoff_wall_line": None},
        "note": "not a lake",
    }
    ctx = _ctx(_geographic(enabled=False))
    ctx.setup.flow = SimpleNamespace(sinks_sources={"lakes": lakes})
    table = LakeRefinementConfig(dam_cell_size=60.0, dam_outlet_disk=True)
    mesh_cfg = MeshConfig(
        engine="triangle", families={"rivers": "none", "geology": "none"}, lake_refinement=table
    )

    inputs = planning_inputs(ctx, mesh_cfg)

    expected = lake_structures({"a": wall}, {"a": first, "b": second}, Point(1.0, 2.0), table)
    assert inputs.lakes == (first, second)
    assert [label for label, *_ in inputs.lake_structures] == ["voile:a", "sill:a-b", "dam_outlet"]
    assert inputs.lake_structures == expected


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
