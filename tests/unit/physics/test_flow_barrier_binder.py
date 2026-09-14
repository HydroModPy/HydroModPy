"""The flow-barrier binders resolve traces onto the runtime payloads.

``apply_cutoff_wall_to_flow`` resolves each lake's ``cutoff_wall`` trace onto
``payload['cutoff_wall_line']``; ``apply_flow_barriers_to_flow`` normalizes the
general ``[flow.sinks_sources.flow_barriers]`` mapping to ``{'barrier', 'line'}``
payloads. Both read inline coords (or a vector file) into a shapely LineString.
"""

from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import FlowBarrierConfig, FlowLakeConfig
from hydromodpy.physics.flow.structure_binders import (
    apply_cutoff_wall_to_flow,
    apply_flow_barriers_to_flow,
)


def test_cutoff_wall_binder_attaches_an_inline_line() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "stageinit": "81.82 m",
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
    lake = FlowLakeConfig.model_validate({"bedleak": 1e-6, "stageinit": "81.82 m"})
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


def test_general_flow_barrier_binder_is_a_noop_when_empty() -> None:
    flow = SimpleNamespace(sinks_sources={"flow_barriers": {}})
    assert apply_flow_barriers_to_flow(flow=flow) is False
