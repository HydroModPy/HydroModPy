"""The FlowBarrierConfig HFB payload (general addon + lake cutoff wall).

A flow barrier carries the trace (inline ``line`` or a ``line_path`` vector
file), the ``depths`` below the model top, and the resistance (``hydchr`` or
``k`` + ``thickness``). It is declared either generally under
``[flow.sinks_sources.flow_barriers.<id>]`` or as a lake's ``cutoff_wall``. The
tests check the geometry / resistance XOR rules, the unit conversions of
``effective_hydchr``, ``extra='forbid'``, that it nests on a lake config and on
the sinks-sources container, and that the binder normalizer carries the lake
wall onto the payload dict.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.physics.flow.sinks_sources import (
    FlowBarrierConfig,
    FlowLakeConfig,
    FlowSinksSourcesConfig,
)
from hydromodpy.physics.flow.structure_binders import _lake_payloads_as_mappings


def test_inline_line_and_hydchr_validate() -> None:
    wall = FlowBarrierConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[10.0], hydchr=1e-9)
    assert wall.effective_hydchr() == pytest.approx(1e-9)
    assert wall.line_path is None


def test_hydchr_unit_is_converted_to_per_second() -> None:
    # 1/day at 8.64e-5 is 1e-9 1/s.
    wall = FlowBarrierConfig(
        line=[[0.0, 0.0], [1.0, 1.0]], depths=[5.0], hydchr=8.64e-5, hydchr_unit="1/day"
    )
    assert wall.effective_hydchr() == pytest.approx(1e-9)


def test_k_and_thickness_derive_hydchr() -> None:
    # hydchr = K / thickness = 1e-8 (m/s) / 0.5 (m) = 2e-8 1/s.
    wall = FlowBarrierConfig(line=[[0.0, 0.0], [10.0, 0.0]], depths=[5.0], k=1e-8, thickness=0.5)
    assert wall.effective_hydchr() == pytest.approx(2e-8)


def test_k_unit_is_converted() -> None:
    # 0.864 m/day = 1e-5 m/s; over 1 m thickness => 1e-5 1/s.
    wall = FlowBarrierConfig(
        line=[[0.0, 0.0], [10.0, 0.0]],
        depths=[5.0],
        k=0.864,
        k_unit="m/day",
        thickness=1.0,
    )
    assert wall.effective_hydchr() == pytest.approx(1e-5)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(line=[[0, 0], [1, 0]], line_path="x.gpkg", depths=[1.0], hydchr=1e-9),  # both geom
        dict(depths=[1.0], hydchr=1e-9),  # no geom
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, k=1e-8, thickness=0.5),  # both R
        dict(line=[[0, 0], [1, 0]], depths=[1.0], k=1e-8),  # partial resistance
        dict(line=[[0, 0]], depths=[1.0], hydchr=1e-9),  # single-vertex line
        dict(line=[[0, 0], [1, 0]], depths=[0.0], hydchr=1e-9),  # non-positive depth
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, hydchr_unit="bogus"),  # bad unit
        dict(line=[[0, 0], [1, 0]], depths=[1.0], hydchr=1e-9, who="me"),  # extra field
    ],
)
def test_invalid_configs_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        FlowBarrierConfig(**kwargs)


def test_nests_as_lake_cutoff_wall_and_survives_the_binder_normalizer() -> None:
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
    assert isinstance(lake.cutoff_wall, FlowBarrierConfig)

    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})
    payloads = _lake_payloads_as_mappings(flow)
    assert isinstance(payloads["reservoir"]["cutoff_wall"], FlowBarrierConfig)


def test_general_flow_barriers_mapping_validates() -> None:
    ss = FlowSinksSourcesConfig.model_validate(
        {
            "flow_barriers": {
                "wall_a": {"line": [[0.0, 0.0], [10.0, 0.0]], "depths": [8.0], "hydchr": 1e-9}
            }
        }
    )
    assert isinstance(ss.flow_barriers["wall_a"], FlowBarrierConfig)
    assert ss.flow_barriers["wall_a"].effective_hydchr() == pytest.approx(1e-9)
