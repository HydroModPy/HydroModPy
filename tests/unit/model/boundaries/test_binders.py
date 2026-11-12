"""Binders that lay barriers, lake geometry and cutoff walls onto the flow payloads.

Coordinates are projected metres, depths and offsets are in m.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.model.boundaries.barriers import (
    apply_flow_barriers_to_flow,
    resolve_barrier_line,
)
from hydromodpy.model.boundaries.cutoff_wall_shore import auto_dam_axis, snap_wall_to_shore
from hydromodpy.model.boundaries.lakes import (
    apply_cutoff_wall_to_flow,
    apply_lake_abacus_to_flow,
    apply_lake_bathymetry_to_flow,
    apply_lake_geometry_to_flow,
)
from hydromodpy.model.sinks_sources.flow_barrier import CutoffWallConfig, FlowBarrierConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from tests._helpers.reservoir_dam import DAM_X, Y0, reservoir, trace


def test_dam_axis_crosses_outlet_flow() -> None:
    # Outlet due north of a tall reservoir: the dam axis runs east-west (constant y)
    # at the downstream edge, spanning the reservoir width.
    tall_reservoir = Polygon([(0, 0), (10, 0), (10, 40), (0, 40)])
    axis = auto_dam_axis(tall_reservoir, (5.0, 60.0))
    (_, y0), (_, y1) = axis.coords[0], axis.coords[-1]
    assert y0 == pytest.approx(40.0) and y1 == pytest.approx(40.0)
    assert axis.centroid.x == pytest.approx(5.0)
    assert axis.length >= 10.0  # the reservoir width, plus the abutment extension


def test_resolve_barrier_line_accepts_preloaded_trace() -> None:
    trace_geom = LineString([(0, 0), (10, 10)])
    cfg = SimpleNamespace(line=None, line_path="wall.geojson")
    line = resolve_barrier_line(cfg, where="test", line_trace=trace_geom)
    assert line.equals(trace_geom)


def test_barrier_line_path_needs_trace() -> None:
    cfg = SimpleNamespace(line=None, line_path="wall.geojson")
    with pytest.raises(ValueError, match="must be loaded"):
        resolve_barrier_line(cfg, where="test")


RESERVOIR_SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
ABACUS = {"stage": [1.0, 2.0], "volume": [10.0, 20.0], "sarea": [5.0, 5.0]}
BATHYMETRY_TIF = Path("/path/to/lake_bathymetry.tif")

ATTACHMENTS = [
    pytest.param(apply_lake_geometry_to_flow, "polygons", RESERVOIR_SQUARE, "polygon", id="polygon"),
    pytest.param(apply_lake_abacus_to_flow, "abacus", ABACUS, "abacus", id="abacus"),
    pytest.param(apply_lake_bathymetry_to_flow, "bathymetry", BATHYMETRY_TIF, "bathymetry", id="bathymetry"),
]  # fmt: skip


@pytest.mark.parametrize(("bind", "argument", "value", "key"), ATTACHMENTS)
def test_lake_attachments(bind, argument, value, key) -> None:
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": {}}})
    assert bind(flow=flow, **{argument: {"reservoir": value}}) is True
    assert flow.sinks_sources["lakes"]["reservoir"][key] == value


# Both barrier binders read inline coordinates into a shapely LineString.


def test_cutoff_wall_inline_line() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "initial_stage": "81.82 m",
            "cutoff_wall": {
                "line": [[331142.0, 6780439.3], [331119.4, 6780718.7]],
                "depths": [10.0],
                "hydchr": 1e-9,
            },
        }
    )
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})

    assert apply_cutoff_wall_to_flow(flow=flow) is True
    payload = flow.sinks_sources["lakes"]["reservoir"]
    line = payload["cutoff_wall_line"]
    assert isinstance(line, LineString)
    assert list(line.coords) == [(331142.0, 6780439.3), (331119.4, 6780718.7)]
    assert isinstance(payload["cutoff_wall"], FlowBarrierConfig)


def test_no_cutoff_wall_is_noop() -> None:
    lake = FlowLakeConfig.model_validate({"bedleak": 1e-6, "initial_stage": "81.82 m"})
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})
    assert apply_cutoff_wall_to_flow(flow=flow) is False


def test_flow_barrier_line_and_config() -> None:
    barrier = FlowBarrierConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[5.0], hydchr=1e-9)
    flow = SimpleNamespace(sinks_sources={"flow_barriers": {"wall_a": barrier}})

    assert apply_flow_barriers_to_flow(flow=flow) is True
    payload = flow.sinks_sources["flow_barriers"]["wall_a"]
    assert list(payload["line"].coords) == [(0.0, 0.0), (10.0, 0.0)]
    assert payload["barrier"] is barrier
    # idempotent: a second pass keeps the resolved payload
    assert apply_flow_barriers_to_flow(flow=flow) is False
    assert list(flow.sinks_sources["flow_barriers"]["wall_a"]["line"].coords) == [
        (0.0, 0.0),
        (10.0, 0.0),
    ]


# A cutoff-wall trace runs 12 m off the flat dam shore, crosses it 30 m inside, or stops 200 m
# away (tests/_helpers/reservoir_dam.py).


def test_trace_off_shore_is_snapped() -> None:
    lake = reservoir()
    wall = snap_wall_to_shore(lake, trace(12.0), 50.0)

    assert wall.gap_m == pytest.approx(12.0)
    assert wall.cut_area_m2 == 0.0
    assert wall.polygon.equals(lake)
    assert wall.shore.distance(lake.exterior) < 1e-6
    assert max(lake.exterior.distance(Point(xy)) for xy in wall.shore.coords) < 1e-6
    dam_shore = lake.exterior.intersection(LineString([(DAM_X, Y0), (DAM_X, Y0 + 800.0)]))
    assert dam_shore.difference(wall.shore.buffer(1e-6)).length == pytest.approx(0.0)
    ends = {wall.line.coords[0], wall.line.coords[-1]}
    assert ends == set(trace(12.0).coords)


def test_trace_crossing_lake_cuts_it() -> None:
    lake = reservoir()
    crossing = trace(-30.0)
    wall = snap_wall_to_shore(lake, crossing, 50.0)

    assert wall.gap_m == 0.0
    assert wall.cut_area_m2 > 0.0
    assert wall.polygon.area == pytest.approx(lake.area - wall.cut_area_m2)
    assert wall.polygon.bounds[2] == pytest.approx(DAM_X - 30.0)
    inside_cut = crossing.intersection(lake)
    assert inside_cut.difference(wall.shore.buffer(1e-6)).length == pytest.approx(0.0)


STUB = LineString([(DAM_X + 50.0, Y0 + 400.0), (DAM_X - 100.0, Y0 + 400.0)])

SNAP_REFUSALS = [
    pytest.param(trace(200.0), r"200\.0 m from the lake shore", id="200 m away"),
    pytest.param(STUB, "without crossing it", id="enters without crossing"),
]


@pytest.mark.parametrize(("line", "match"), SNAP_REFUSALS)
def test_snap_refusals(line, match) -> None:
    with pytest.raises(ValueError, match=match):
        snap_wall_to_shore(reservoir(), line, 50.0)


def _flow(offset: float, **wall: object) -> SimpleNamespace:
    coords = [list(xy) for xy in trace(offset).coords]
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "initial_stage": "81 m",
            "cutoff_wall": {"line": coords, "depths": [10.0], "hydchr": 1e-9, **wall},
        }
    )
    payload = {name: getattr(lake, name) for name in type(lake).model_fields}
    payload["polygon"] = reservoir()
    return SimpleNamespace(sinks_sources={"lakes": {"reservoir": payload}})


def test_binder_records_wall_and_trace() -> None:
    flow = _flow(12.0)
    assert apply_cutoff_wall_to_flow(flow=flow) is True
    payload = flow.sinks_sources["lakes"]["reservoir"]

    assert isinstance(payload["cutoff_wall"], CutoffWallConfig)
    assert payload["cutoff_wall_trace"].equals(trace(12.0))
    assert payload["cutoff_wall_line"].distance(reservoir()) < 1e-6
    assert payload["cutoff_wall_shore"].length > 0.0


def test_binder_cuts_footprint() -> None:
    flow = _flow(-30.0)
    apply_cutoff_wall_to_flow(flow=flow)
    assert flow.sinks_sources["lakes"]["reservoir"]["polygon"].area < reservoir().area


def test_binder_refuses_far_trace() -> None:
    with pytest.raises(ConfigError, match=r"lakes\.reservoir\.cutoff_wall.*200\.0 m"):
        apply_cutoff_wall_to_flow(flow=_flow(200.0))


def test_wider_tolerance_reaches_trace() -> None:
    flow = _flow(200.0, snap_tolerance=250.0)
    apply_cutoff_wall_to_flow(flow=flow)
    assert flow.sinks_sources["lakes"]["reservoir"]["cutoff_wall_line"].distance(reservoir()) < 1e-6
