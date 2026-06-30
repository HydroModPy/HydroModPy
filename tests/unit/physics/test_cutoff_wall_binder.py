"""apply_cutoff_wall_to_flow resolves the dam-wall trace onto the lake payload.

The wall trace is declared on ``FlowLakeConfig.cutoff_wall`` (inline ``line`` or
a ``line_path`` vector file). The binder reads it into a shapely LineString and
attaches it as ``payload['cutoff_wall_line']`` so the HFB builder can map it onto
the mesh faces. A lake without a cutoff_wall is left untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import CutoffWallConfig, FlowLakeConfig
from hydromodpy.physics.flow.structure_binders import apply_cutoff_wall_to_flow


def test_binder_attaches_an_inline_wall_line() -> None:
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

    attached = apply_cutoff_wall_to_flow(flow=flow)

    assert attached is True
    payload = flow.sinks_sources["lakes"]["reservoir"]
    line = payload["cutoff_wall_line"]
    assert isinstance(line, LineString)
    assert list(line.coords) == [(331142.0, 6780439.3), (331119.4, 6780718.7)]
    # the parameters stay on the payload for the solver-side resolver
    assert isinstance(payload["cutoff_wall"], CutoffWallConfig)


def test_binder_is_a_noop_without_a_cutoff_wall() -> None:
    lake = FlowLakeConfig.model_validate({"bedleak": 1e-6, "stageinit": "81.82 m"})
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})

    attached = apply_cutoff_wall_to_flow(flow=flow)

    assert attached is False


def test_binder_handles_a_dict_payload() -> None:
    # A lake payload already normalized to a dict (e.g. after another binder ran)
    # keeps its cutoff_wall config object and still resolves the line.
    wall = CutoffWallConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[5.0], hydchr=1e-9)
    flow = SimpleNamespace(
        sinks_sources={"lakes": {"reservoir": {"bedleak": 1e-6, "cutoff_wall": wall}}}
    )

    attached = apply_cutoff_wall_to_flow(flow=flow)

    assert attached is True
    line = flow.sinks_sources["lakes"]["reservoir"]["cutoff_wall_line"]
    assert list(line.coords) == [(0.0, 0.0), (10.0, 0.0)]
