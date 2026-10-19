"""A declared cutoff-wall trace is laid on the lake shore it faces.

The trace runs 12 m downstream of the flat dam shore of the reservoir, crosses
it 30 m inside, or stops 200 m away (``tests/_helpers/reservoir_dam.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.flow.cutoff_wall_shore import snap_wall_to_shore
from hydromodpy.physics.flow.sinks_sources import CutoffWallConfig, FlowLakeConfig
from hydromodpy.physics.flow.structure_binders import apply_cutoff_wall_to_flow
from tests._helpers.reservoir_dam import DAM_X, Y0, reservoir, trace


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


def test_the_wall_runs_with_the_lake_on_its_left() -> None:
    lake = reservoir()
    wall = snap_wall_to_shore(lake, trace(12.0), 50.0)
    middle = wall.shore.project(wall.shore.interpolate(0.5, normalized=True))
    before = np.array(wall.shore.interpolate(middle - 1.0).coords[0])
    after = np.array(wall.shore.interpolate(middle + 1.0).coords[0])
    tangent = after - before
    left = 0.5 * (before + after) + 2.0 * np.array([-tangent[1], tangent[0]]) / np.hypot(*tangent)
    assert lake.contains(Point(left))


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
            "stageinit": "81 m",
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
