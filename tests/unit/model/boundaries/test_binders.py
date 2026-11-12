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


def test_auto_dam_axis_is_perpendicular_to_the_outlet_flow() -> None:
    # Outlet due north of a tall reservoir: the dam axis runs east-west (constant y)
    # at the downstream edge, spanning the reservoir width.
    reservoir = Polygon([(0, 0), (10, 0), (10, 40), (0, 40)])
    axis = auto_dam_axis(reservoir, (5.0, 60.0))
    (x0, y0), (x1, y1) = axis.coords[0], axis.coords[-1]
    assert y0 == pytest.approx(40.0) and y1 == pytest.approx(40.0)
    assert axis.centroid.x == pytest.approx(5.0)
    assert axis.length >= 10.0  # the reservoir width, plus the abutment extension


def test_resolve_barrier_line_accepts_preloaded_trace() -> None:
    trace_geom = LineString([(0, 0), (10, 10)])
    cfg = SimpleNamespace(line=None, line_path="wall.geojson")
    line = resolve_barrier_line(cfg, where="test", line_trace=trace_geom)
    assert line.equals(trace_geom)


def test_resolve_barrier_line_refuses_line_path_without_trace() -> None:
    cfg = SimpleNamespace(line=None, line_path="wall.geojson")
    with pytest.raises(ValueError, match="must be loaded"):
        resolve_barrier_line(cfg, where="test")


def test_apply_lake_geometry_attaches_polygons() -> None:
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": {}}})
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert apply_lake_geometry_to_flow(flow=flow, polygons={"reservoir": poly}) is True
    assert flow.sinks_sources["lakes"]["reservoir"]["polygon"].equals(poly)


def test_apply_lake_abacus_attaches_curves() -> None:
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": {}}})
    abacus_data = {"stage": [1.0, 2.0], "volume": [10.0, 20.0], "sarea": [5.0, 5.0]}
    assert apply_lake_abacus_to_flow(flow=flow, abacus={"reservoir": abacus_data}) is True
    assert flow.sinks_sources["lakes"]["reservoir"]["abacus"] == abacus_data


def test_apply_lake_bathymetry_attaches_path() -> None:
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": {}}})
    path = Path("/path/to/lake_bathymetry.tif")
    assert apply_lake_bathymetry_to_flow(flow=flow, bathymetry={"reservoir": path}) is True
    assert flow.sinks_sources["lakes"]["reservoir"]["bathymetry"] == path


# The flow-barrier binders resolve traces onto the runtime payloads.
#
# ``apply_cutoff_wall_to_flow`` resolves each lake's ``cutoff_wall`` trace onto
# ``payload['cutoff_wall_line']``; ``apply_flow_barriers_to_flow`` normalizes the
# general ``[flow.sinks_sources.flow_barriers]`` mapping to ``{'barrier', 'line'}``
# payloads. Both read inline coords (or a vector file) into a shapely LineString.


def test_cutoff_wall_binder_attaches_an_inline_line() -> None:
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


def test_cutoff_wall_binder_is_a_noop_without_a_wall() -> None:
    lake = FlowLakeConfig.model_validate({"bedleak": 1e-6, "initial_stage": "81.82 m"})
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})
    assert apply_cutoff_wall_to_flow(flow=flow) is False


def test_general_flow_barrier_binder_attaches_line_and_config() -> None:
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


# A declared cutoff-wall trace is laid on the lake shore it faces.
#
# The trace runs 12 m downstream of the flat dam shore of the reservoir, crosses
# it 30 m inside, or stops 200 m away (``tests/_helpers/reservoir_dam.py``).


def test_a_trace_12_m_off_the_shore_is_laid_on_it_and_keeps_its_wings() -> None:
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


def test_a_trace_crossing_the_lake_cuts_it_and_the_wall_lies_on_the_cut() -> None:
    lake = reservoir()
    crossing = trace(-30.0)
    wall = snap_wall_to_shore(lake, crossing, 50.0)

    assert wall.gap_m == 0.0
    assert wall.cut_area_m2 > 0.0
    assert wall.polygon.area == pytest.approx(lake.area - wall.cut_area_m2)
    assert wall.polygon.bounds[2] == pytest.approx(DAM_X - 30.0)
    inside_cut = crossing.intersection(lake)
    assert inside_cut.difference(wall.shore.buffer(1e-6)).length == pytest.approx(0.0)


def test_a_trace_200_m_away_is_refused_with_the_gap() -> None:
    with pytest.raises(ValueError, match=r"200\.0 m from the lake shore"):
        snap_wall_to_shore(reservoir(), trace(200.0), 50.0)


def test_a_trace_that_enters_the_lake_without_crossing_it_is_refused() -> None:
    stub = LineString([(DAM_X + 50.0, Y0 + 400.0), (DAM_X - 100.0, Y0 + 400.0)])
    with pytest.raises(ValueError, match="without crossing it"):
        snap_wall_to_shore(reservoir(), stub, 50.0)


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


def test_the_binder_records_the_wall_on_the_shore_and_the_declared_trace() -> None:
    flow = _flow(12.0)
    assert apply_cutoff_wall_to_flow(flow=flow) is True
    payload = flow.sinks_sources["lakes"]["reservoir"]

    assert isinstance(payload["cutoff_wall"], CutoffWallConfig)
    assert payload["cutoff_wall_trace"].equals(trace(12.0))
    assert payload["cutoff_wall_line"].distance(reservoir()) < 1e-6
    assert payload["cutoff_wall_shore"].length > 0.0


def test_the_binder_cuts_the_footprint_a_trace_crosses() -> None:
    flow = _flow(-30.0)
    apply_cutoff_wall_to_flow(flow=flow)
    assert flow.sinks_sources["lakes"]["reservoir"]["polygon"].area < reservoir().area


def test_the_binder_refuses_a_trace_beyond_the_snap_tolerance_naming_the_lake() -> None:
    with pytest.raises(ConfigError, match=r"lakes\.reservoir\.cutoff_wall.*200\.0 m"):
        apply_cutoff_wall_to_flow(flow=_flow(200.0))


def test_a_wider_snap_tolerance_reaches_a_farther_trace() -> None:
    flow = _flow(200.0, snap_tolerance=250.0)
    apply_cutoff_wall_to_flow(flow=flow)
    assert flow.sinks_sources["lakes"]["reservoir"]["cutoff_wall_line"].distance(reservoir()) < 1e-6


# A built structure's geometry and a coupling rule are not search targets.
#
# ``FlowBarrierConfig.crest_elevation`` / ``base_elevation`` and
# ``FlowReachNetworkConfig.outflow_value`` were deliberately left without a
# ``Calibrable`` annotation: the wall's elevations trade off against ``hydchr``
# (a deeper foot and a lower ``hydchr`` reduce under-dam flow the same way), and
# the MVR ``outflow_value`` is a coupling rule, not a hydraulic property. Letting
# a search move any of them buys fit through equifinality or through masking a
# structural error, rather than resolving a real physical unknown. This states
# the boundary the catalog draws rather than reciting the three names, so a
# sibling field that IS a property is asserted calibratable too.
